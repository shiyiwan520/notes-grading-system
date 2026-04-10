"""
grader.py — Gemini AI 評分模組
6 級分制，3 個評分面向
"""

import os
import re
import json
import streamlit as st
from typing import Tuple
import google.generativeai as genai

VALID_SCORES = {0, 1, 2, 3, 4, 5}

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
  "justification": "<string: 80-120 words in English explaining score based on the 3 criteria>",
  "needs_review": <boolean: true if mixed language, very unusual content, or low confidence>
}"""


def _get_model():
    api_key = st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.5-flash")


def grade(text: str, key_concepts: str = "") -> Tuple[int, str, bool]:
    if not text or len(text.strip()) < 10:
        return 0, "Submission is empty or unreadable. Score: 0 (Missing).", False

    if _chinese_ratio(text) > 0.70:
        return 0, "Notes are primarily in Chinese. English notes are required. Score: 0 (Missing).", False

    prompt = BASE_SYSTEM_PROMPT
    if key_concepts.strip():
        prompt += (
            f"\n\nThis week's key concepts to assess for Content Coverage:\n{key_concepts.strip()}\n"
            "Specifically check whether these concepts appear in the student's notes."
        )

    sample_text = text[:4000]
    user_msg = f"Grade the following student English notes:\n\n---\n{sample_text}\n---"

    try:
        model = _get_model()
        response = model.generate_content(
            [prompt, user_msg],
            generation_config={"max_output_tokens": 1024, "temperature": 0.2}
        )
        return _parse_response(response.text.strip())
    except Exception as e:
        return 0, f"AI grading failed. Manual review required. ({str(e)[:80]})", True


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
        justification = str(data.get("justification", "No justification provided."))[:600]
        needs_review = bool(data.get("needs_review", False))
        return score, justification, needs_review
    except Exception:
        score_match = re.search(r'"score"\s*:\s*(\d+)', raw)
        if score_match:
            score = int(score_match.group(1))
            if score not in VALID_SCORES:
                score = 0
            just_match = re.search(r'"justification"\s*:\s*"([^"]{10,})', raw)
            justification = (just_match.group(1)[:300] + "...") if just_match else "See raw response."
            return score, justification, True
        return 0, f"Could not parse AI response. Raw: {raw[:200]}", True


def _chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total = len([c for c in text if c.strip()])
    return chinese / total if total else 0.0
