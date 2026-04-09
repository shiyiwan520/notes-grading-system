"""
grader.py — Gemini AI 評分模組
"""

import os
import re
import json
import streamlit as st
from typing import Tuple
import google.generativeai as genai

VALID_SCORES = {0, 2, 3, 4, 5, 6, 7}

BASE_SYSTEM_PROMPT = """You are an experienced English language teacher grading student English notes.
Evaluate the notes and return ONLY a JSON object with no extra text, no markdown fences.

JSON format:
{
  "score": <integer: 0, 2, 3, 4, 5, 6, or 7>,
  "justification": "<string: up to 100 words in English explaining the score>",
  "needs_review": <boolean>
}

Scoring rubric:
  7 = Outstanding: Exceptionally rich content, comprehensive key concepts, excellent English
  6 = Excellent: Very rich content, covers most key concepts, very good English
  5 = Very Good: Good depth, covers important concepts, good English with minor errors
  4 = Good: Adequate content, covers basic concepts, acceptable English
  3 = Satisfactory: Limited content, some concepts, noticeable English errors
  2 = Pass: Minimal content, barely covers concepts, significant English errors
  0 = Fail: Primarily Chinese, nearly empty, or completely off-topic

Rules:
- Notes primarily or entirely in Chinese → score MUST be 0
- Mixed language (>30% Chinese) → score 0 or 2 max, needs_review = true
- Content very short (<50 words) → score 2 max
- needs_review = true when: mixed language, unusual content, or low confidence
"""


def _get_client():
    api_key = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.5-flash")


def grade(text: str, key_concepts: str = "") -> Tuple[int, str, bool]:
    """
    評分主函式
    key_concepts: 老師設定的本週重點概念（可為空）
    回傳 (score, justification, needs_review)
    """
    if not text or len(text.strip()) < 10:
        return 0, "Submission is empty or unreadable. Score: 0 (Fail).", False

    # 快速語言預檢
    if _chinese_ratio(text) > 0.70:
        return 0, "Notes are primarily in Chinese. English notes are required. Score: 0 (Fail).", False

    # 建立 prompt（加入本週重點概念）
    prompt = BASE_SYSTEM_PROMPT
    if key_concepts.strip():
        prompt += f"\n\nThis week's key concepts to assess: {key_concepts.strip()}\nPlease specifically evaluate whether the student's notes cover these concepts."

    sample_text = text[:3000]
    user_msg = f"Grade the following student English notes:\n\n---\n{sample_text}\n---"

    try:
        model = _get_client()
        response = model.generate_content(
            [prompt, user_msg],
            generation_config={"max_output_tokens": 1024, "temperature": 0.2}
        )
        raw = response.text.strip()
        return _parse_response(raw)
    except Exception as e:
        return 0, f"AI grading failed. Manual review required. ({str(e)[:80]})", True


def _parse_response(raw: str) -> Tuple[int, str, bool]:
    try:
        cleaned = re.sub(r"```json|```", "", raw).strip()
        # 若 JSON 被截斷，嘗試補上結尾
        if not cleaned.endswith("}"):
            # 找最後一個完整的 key-value，補上結尾
            last_quote = cleaned.rfind('"')
            if last_quote > 0:
                cleaned = cleaned[:last_quote + 1] + "}"
        data = json.loads(cleaned)
        score = int(data.get("score", 0))
        if score not in VALID_SCORES:
            score = 0
        justification = str(data.get("justification", "No justification provided."))[:500]
        needs_review = bool(data.get("needs_review", False))
        return score, justification, needs_review
    except Exception:
        # 嘗試用 regex 直接抓 score
        score_match = re.search(r'"score"\s*:\s*(\d+)', raw)
        if score_match:
            score = int(score_match.group(1))
            if score not in VALID_SCORES:
                score = 0
            just_match = re.search(r'"justification"\s*:\s*"([^"]{10,})', raw)
            justification = just_match.group(1)[:300] + "..." if just_match else "See raw response."
            return score, justification, True
        return 0, f"Could not parse AI response. Raw: {raw[:200]}", True


def _chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total = len([c for c in text if c.strip()])
    return chinese / total if total else 0.0
