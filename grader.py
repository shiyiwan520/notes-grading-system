"""
grader.py — Gemini AI 評分模組
6 級分制，3 個評分面向
含：retry/backoff、模型可設定、request logging
"""

import os
import re
import json
import time
import streamlit as st
from datetime import datetime, timezone, timedelta
from typing import Tuple, Dict
import google.generativeai as genai

VALID_SCORES = {0, 1, 2, 3, 4, 5}

# 預設模型（可在 Settings 覆蓋）
DEFAULT_MODEL = "gemini-2.5-flash-lite"

BASE_SYSTEM_PROMPT = """You are an experienced university teacher grading student English notes.
The course allows students to use AI tools to help organize their notes.
Therefore, do NOT penalize for AI-assisted writing. Focus on content quality, not English expression.

Evaluate based on these 3 criteria (weights):

1. Content Coverage (40%) — Does the note cover the key lecture concepts?
   - Are the main topics present?
   - Are important details, examples, or formulas included?

2. Organization / Clarity (30%) — Is the note well-structured and easy to follow?
   - Clear headings, sections, or logical flow?
   - Not just a dump of text — shows intentional organization?

3. Understanding / Value Added (30%) — Does the note show comprehension beyond copy-paste?
   - Any student's own summaries, connections, or annotations?
   - Evidence of processing the material, not just reproducing it?

Scoring rubric (6-level scale):
  5 = Excellent: Covers virtually all key concepts with strong organization and clear evidence of understanding/synthesis
  4 = Very Good: Covers most key concepts, well-organized, some personal understanding shown
  3 = Good: Covers main concepts adequately, reasonably organized, basic understanding evident
  2 = Fair: Covers some concepts but gaps are noticeable; organization is weak or unclear
  1 = Fail: Very limited coverage, poorly organized, little evidence of understanding
  0 = Missing: Blank, unreadable, entirely in Chinese, or completely off-topic

Key distinctions:
- Good vs Very Good: Very Good has more complete coverage AND better organization
- Very Good vs Excellent: Excellent shows synthesis, connections, or insights beyond just listing facts
- Fair vs Fail: Fair has at least some relevant content; Fail has almost none

IMPORTANT: If the notes are primarily or entirely in Chinese, score MUST be 0.
If content is very short (<50 words of substance), score 2 max.

Respond ONLY with valid JSON, no markdown fences, no extra text:
{
  "score": <integer 0-5>,
  "justification": "<string: 150-200 words in English. For each of the 3 criteria (Content Coverage, Organization, Understanding), briefly state what was strong or weak, then explain the final score>",
  "needs_review": <boolean: true if mixed language, very unusual content, or low confidence>
}"""


def _get_model_name() -> str:
    """從 settings 讀取模型名稱，沒設定就用預設值"""
    try:
        import storage
        settings = storage.get_settings()
        return settings.get("ai_model", DEFAULT_MODEL) or DEFAULT_MODEL
    except Exception:
        return DEFAULT_MODEL


def _get_model(model_name: str):
    api_key = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name)


def grade(text: str, key_concepts: str = "") -> Tuple[int, str, bool, Dict]:
    """
    回傳 (score, justification, needs_review, log_info)
    log_info 包含 model_name, retry_count, request_status, input_tokens_est, graded_at
    """
    tw_tz = timezone(timedelta(hours=8))
    model_name = _get_model_name()

    # 預估 input tokens（粗估：字元數 / 4）
    input_tokens_est = len(text) // 4

    if not text or len(text.strip()) < 10:
        return 0, "Submission is empty or unreadable. Score: 0 (Missing).", False, {
            "model_name": model_name, "retry_count": 0,
            "request_status": "cached", "input_tokens_est": 0,
            "graded_at": datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S"),
        }

    if _chinese_ratio(text) > 0.70:
        return 0, "Notes are primarily in Chinese. English notes are required. Score: 0 (Missing).", False, {
            "model_name": model_name, "retry_count": 0,
            "request_status": "cached", "input_tokens_est": input_tokens_est,
            "graded_at": datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S"),
        }

    prompt = BASE_SYSTEM_PROMPT
    if key_concepts.strip():
        prompt += (
            f"\n\nThis week's key concepts to assess for Content Coverage:\n{key_concepts.strip()}\n"
            "Specifically check whether these concepts appear in the student's notes."
        )

    # 均勻抽樣：避免只評到目錄頁
    if len(text) <= 8000:
        sample_text = text
    else:
        mid = len(text) // 2
        sample_text = (
            text[:3000]
            + "\n\n[... middle section ...]\n\n"
            + text[mid-1500:mid+1500]
            + "\n\n[... end section ...]\n\n"
            + text[-2000:]
        )

    user_msg = f"Grade the following student English notes:\n\n---\n{sample_text}\n---"

    # Retry with backoff：最多 3 次，遇到 429 才 retry
    MAX_RETRIES = 3
    BACKOFF_SECONDS = [0, 30, 60]  # 第1次不等，第2次等30秒，第3次等60秒

    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            wait = BACKOFF_SECONDS[attempt]
            time.sleep(wait)
        try:
            model = _get_model(model_name)
            response = model.generate_content(
                [prompt, user_msg],
                generation_config={"max_output_tokens": 1024, "temperature": 0.2}
            )
            score, justification, needs_review = _parse_response(response.text.strip())
            return score, justification, needs_review, {
                "model_name": model_name,
                "retry_count": attempt,
                "request_status": "success",
                "input_tokens_est": input_tokens_est,
                "graded_at": datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as e:
            err_str = str(e)
            is_429 = "429" in err_str or "quota" in err_str.lower() or "exhausted" in err_str.lower()
            if is_429 and attempt < MAX_RETRIES - 1:
                continue  # retry
            # 最後一次或非 429 錯誤，直接回傳失敗
            return 0, f"AI grading failed. Manual review required. ({err_str[:120]})", True, {
                "model_name": model_name,
                "retry_count": attempt,
                "request_status": "failed",
                "input_tokens_est": input_tokens_est,
                "graded_at": datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S"),
            }

    # 不應該到這裡，保險用
    return 0, "AI grading failed. Manual review required.", True, {
        "model_name": model_name, "retry_count": MAX_RETRIES,
        "request_status": "failed", "input_tokens_est": input_tokens_est,
        "graded_at": datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S"),
    }


def _parse_response(raw: str) -> Tuple[int, str, bool]:
    try:
        cleaned = re.sub(r"```json|```", "", raw).strip()
        if not cleaned.endswith("}"):
            last_quote = cleaned.rfind('"')
            if last_quote > 0:
                cleaned = cleaned[:last_quote + 1] + "}"
        data = json.loads(cleaned)
        score = int(data.get("score", 0))
        if score not in VALID_SCORES:
            score = 0
        justification = str(data.get("justification", "No justification provided."))
        needs_review = bool(data.get("needs_review", False))
        return score, justification, needs_review
    except Exception:
        score_match = re.search(r'"score"\s*:\s*(\d+)', raw)
        if score_match:
            score = int(score_match.group(1))
            if score not in VALID_SCORES:
                score = 0
            just_match = re.search(r'"justification"\s*:\s*"([^"]{10,})', raw)
            justification = just_match.group(1) if just_match else "See raw response."
            return score, justification, True
        return 0, f"Could not parse AI response. Raw: {raw[:200]}", True


def _chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total = len([c for c in text if c.strip()])
    return chinese / total if total else 0.0
