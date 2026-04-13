"""
grader.py
AI 評分模組 — Gemini API，四維度加權，7 級制

評分面向：
  A. AI Use Strategy / Prompt Quality     (25%)
  B. Knowledge Restructuring Quality      (30%)
  C. Learning Material Value              (25%)
  D. Personal Learning Trace              (20%)

整體等級（7 級制）：
  Perfect / Excellent / Great / Good / Average / Fair / Poor / Missing

─────────────────────────────────────────────
Changelog
─────────────────────────────────────────────
v4.0  2026-04-13  Converge to fixed model, short JSON output, correct error codes
  - FIXED_MODEL = "gemini-2.5-flash-lite" (only model; no switching)
  - Removed: FALLBACK_MODEL, get_active_model(), model whitelist, preview names
  - JSON output: short format (dimension_scores, weighted_score, grade,
    language_compliance, needs_review, brief_reason) — removed key_evidence
  - Error handling: 429 → rate_limit; 404/NOT_FOUND → invalid_model (not rate_limit)
  - grade() model param kept for call-site compat but always uses FIXED_MODEL
  - max_output_tokens reduced to 800 (short JSON needs less)

v3.5  2026-04-13  Fix KeyError model_name — add required keys to all return paths
v3.4  2026-04-13  Add FIXED_MODEL alias + get_active_model()
v3.3  2026-04-13  Migrate from google-generativeai to google-genai SDK
v3.2  2026-04-13  Chinese-dominant justification message fix
v3.1  2026-04-13  Chinese-dominant reclassified from Poor → Missing
v3.0  2026-04-13  7-level grade system + rubric calibration
─────────────────────────────────────────────
"""

import os
import re
import time
import json
import random
import logging
from datetime import datetime
from typing import Tuple

from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 模型設定（固定，不從 settings 切換）
# ─────────────────────────────────────────────
FIXED_MODEL   = "gemini-2.5-flash-lite"
DEFAULT_MODEL = FIXED_MODEL  # alias for call-site compatibility

# ─────────────────────────────────────────────
# 等級 → 數字分數（Supabase 相容）
# ─────────────────────────────────────────────
GRADE_TO_SCORE = {
    "Perfect":   5,
    "Excellent": 5,
    "Great":     4,
    "Good":      3,
    "Average":   2,
    "Fair":      1,
    "Poor":      1,
    "Missing":   0,
}


def _score_to_grade(weighted: float) -> str:
    if weighted >= 4.7:   return "Perfect"
    elif weighted >= 4.1: return "Excellent"
    elif weighted >= 3.5: return "Great"
    elif weighted >= 2.9: return "Good"
    elif weighted >= 2.2: return "Average"
    elif weighted >= 1.5: return "Fair"
    else:                 return "Poor"


# ─────────────────────────────────────────────
# 系統 Prompt（短版 JSON 輸出）
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """You are an academic grading assistant evaluating English study notes submitted by graduate students in an AI Classification course. The professor allows and encourages AI tool use. Your task is to assess how well the student used AI to create high-quality learning materials.

Evaluate the notes across FOUR dimensions. For each dimension, assign a score from 1 to 5. Then compute a weighted final score.

---

## DIMENSION A — AI Use Strategy / Prompt Quality (Weight: 25%)

Look for: Is the prompt included in the notes? If yes, assess its quality.

5 — Highly strategic: clear learner background, specific source materials listed, detailed output requirements, explicit learning goals.
4 — Partially strategic: specifies focus, format, or personal context, but not all elements present.
3 — Functional but generic: clear task instructions but lacks learner background or strategic framing.
2 — Vague: generic one-line instruction with no strategy (e.g. "summarize the lecture").
1 — No prompt shown, or a single very short instruction with no context.

If no prompt is visible, default to score 2 unless strong indirect evidence of AI strategy exists.

---

## DIMENSION B — Knowledge Restructuring Quality (Weight: 30%)

This is the most important dimension.

### Does NOT count as high-quality restructuring:
- Renaming slide headings into note headings
- Bullet-point listing of definitions
- Summary rewriting with minor paraphrasing
- Presenting content in the same order as the original source

### Counts as GENUINE restructuring (needed for score 4-5):
- Question-driven section design
- Concept comparison tables built by the student
- Cross-source integration (slides + video + own notes)
- Student-invented logical frameworks or mnemonics
- Synthesis of multiple concepts into a new unified model

5 — Multiple genuine restructuring techniques throughout
4 — At least one clear genuine restructuring technique
3 — Mostly summarized, but with one minor structural choice
2 — Well-organized summary: logical but follows source order
1 — Bullet-point dump or near-verbatim copy

CRITICAL: Do NOT raise B above 3 for well-organized summaries. Organization is not restructuring.

---

## DIMENSION C — Learning Material Value (Weight: 25%)

5 — Comprehensive; fully sufficient as a standalone study resource
4 — Covers most key concepts well; minor gaps
3 — Covers main topics but lacks depth; adequate but not ideal
2 — Partial coverage; missing multiple key points
1 — Very thin content; major gaps

---

## DIMENSION D — Personal Learning Trace (Weight: 20%)

Accept ANY of:
- First-person observations, doubts, or connections
- Personal naming conventions or student-invented mnemonics
- Connection to student's own field or prior knowledge
- Prompt design revealing personal learning needs
- Section choices reflecting student's own learning priorities

5 — Pervasive personal trace throughout
4 — At least one form clearly present and genuine
3 — Generic reflection section, or minor personal framing in one place
2 — Barely any personalization
1 — No trace; entirely generic

---

## SCORING LOGIC

weighted_score = (A x 0.25) + (B x 0.30) + (C x 0.25) + (D x 0.20)
Round to 1 decimal place.

Grade boundaries:
  4.7-5.0 -> Perfect
  4.1-4.6 -> Excellent
  3.5-4.0 -> Great
  2.9-3.4 -> Good
  2.2-2.8 -> Average
  1.5-2.1 -> Fair
  1.0-1.4 -> Poor

SOFT CEILING: Cap at "Good" only when ALL THREE are true: D=1, B<=2, C<=3.

CALIBRATION:
  - Well-organized summary -> Average to Good (NOT Great or above)
  - Great requires B >= 4, OR (A >= 4 AND D >= 4 AND B >= 3)
  - Excellent requires B >= 4 AND D >= 3 AND A >= 3
  - Perfect requires B = 5 AND (D >= 4 OR A = 5) AND C >= 4

---

## LANGUAGE COMPLIANCE

- english_compliant: >70% English (occasional Chinese annotations are fine, do NOT reduce score)
- mixed_chinese_heavy: >30% Chinese but not dominant
- chinese_dominant: >70% Chinese

---

## OUTPUT FORMAT

Return ONLY a valid JSON object. No preamble, no markdown fences, no text outside the JSON.

{
  "dimension_scores": {
    "A_ai_strategy": <1-5>,
    "B_knowledge_restructuring": <1-5>,
    "C_learning_material_value": <1-5>,
    "D_personal_trace": <1-5>
  },
  "weighted_score": <float, 1 decimal place>,
  "grade": "<Perfect | Excellent | Great | Good | Average | Fair | Poor>",
  "language_compliance": "<english_compliant | mixed_chinese_heavy | chinese_dominant>",
  "needs_review": <true | false>,
  "brief_reason": "<1 sentence summarising the key strength or weakness>"
}
"""


# ─────────────────────────────────────────────
# 內部工具函式
# ─────────────────────────────────────────────
def _chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_chars   = len([c for c in text if c.strip()])
    return chinese_chars / total_chars if total_chars > 0 else 0.0


def _detect_language(ratio: float) -> str:
    if ratio > 0.70:   return "chinese_dominant"
    elif ratio > 0.30: return "mixed_chinese_heavy"
    else:              return "english_compliant"


def _get_client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    return genai.Client(api_key=api_key)


def _build_detail(grade_str: str, weighted: float, dim_scores: dict,
                   lang: str, brief_reason: str,
                   request_status: str, retry_count: int = 0) -> dict:
    return {
        "grade":               grade_str,
        "weighted_score":      weighted,
        "dimension_scores":    dim_scores,
        "language_compliance": lang,
        "brief_reason":        brief_reason,
        "model_name":          FIXED_MODEL,
        "graded_at":           datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "retry_count":         retry_count,
        "request_status":      request_status,
        "input_tokens_est":    0,
    }


def _build_justification(grade_str: str, weighted: float,
                          a: int, b: int, c: int, d: int,
                          brief_reason: str) -> str:
    return (
        f"Grade: {grade_str} (Weighted: {weighted}/5.0) | "
        f"A:{a} B:{b} C:{c} D:{d} | {brief_reason}"
    )[:700]


def _parse_response(raw: str):
    """Parse short JSON from Gemini.
    Returns (grade_str, weighted, a, b, c, d, lang, brief_reason, needs_review)
    """
    grade_str    = "Average"
    weighted     = 2.5
    a = b = c = d = 2
    lang         = "english_compliant"
    brief_reason = ""
    needs_review = False

    try:
        cleaned = re.sub(r"```json|```", "", raw).strip()
        data    = json.loads(cleaned)

        dims = data.get("dimension_scores", {})
        a    = int(dims.get("A_ai_strategy",           2))
        b    = int(dims.get("B_knowledge_restructuring", 2))
        c    = int(dims.get("C_learning_material_value", 2))
        d    = int(dims.get("D_personal_trace",          2))

        weighted     = round(float(data.get("weighted_score",
                             a*0.25 + b*0.30 + c*0.25 + d*0.20)), 1)
        grade_str    = data.get("grade", _score_to_grade(weighted))
        lang         = data.get("language_compliance", "english_compliant")
        brief_reason = str(data.get("brief_reason", ""))[:300]
        needs_review = bool(data.get("needs_review", False))

    except Exception:
        try:
            m = re.search(r'"weighted_score"\s*:\s*([\d.]+)', raw)
            if m:
                weighted  = round(float(m.group(1)), 1)
                grade_str = _score_to_grade(weighted)
            for key, attr in [
                ("A_ai_strategy", "a"), ("B_knowledge_restructuring", "b"),
                ("C_learning_material_value", "c"), ("D_personal_trace", "d")
            ]:
                mm = re.search(rf'"{key}"\s*:\s*(\d)', raw)
                if mm:
                    val = int(mm.group(1))
                    if   attr == "a": a = val
                    elif attr == "b": b = val
                    elif attr == "c": c = val
                    elif attr == "d": d = val
            br = re.search(r'"brief_reason"\s*:\s*"([^"]+)"', raw)
            if br:
                brief_reason = br.group(1)[:300]
            needs_review = True
        except Exception:
            pass

    return grade_str, weighted, a, b, c, d, lang, brief_reason, needs_review


# ─────────────────────────────────────────────
# 主要評分函式
# ─────────────────────────────────────────────
def grade(
    text: str,
    key_concepts: str = "",
    model: str = FIXED_MODEL,   # kept for call-site compat; always uses FIXED_MODEL
    max_retries: int = 3,
) -> Tuple[int, str, bool, dict]:
    """
    Returns: (final_score, justification, needs_review, detail_dict)

    detail_dict keys:
        grade, weighted_score, dimension_scores, language_compliance,
        brief_reason, model_name, graded_at, retry_count,
        request_status, input_tokens_est
    """
    _model = FIXED_MODEL  # always fixed; ignore caller's model arg

    # ── 空內容 ──────────────────────────────────────────────────────
    text_len = len(text.strip()) if text else 0
    logger.info(f"[grader.grade] text_len={text_len}")

    if not text or text_len < 10:
        logger.info("[grader.grade] PATH=empty_or_unreadable (len<10)")
        detail = _build_detail(
            "Missing", 0.0,
            {"A_ai_strategy": 0, "B_knowledge_restructuring": 0,
             "C_learning_material_value": 0, "D_personal_trace": 0},
            "unknown",
            "Submission is empty, unreadable, or scan-only.",
            request_status="skipped")
        return 0, "Submission is empty, unreadable, or scan-only. Grade: Missing.", True, detail

    # ── 語言預檢 ────────────────────────────────────────────────────
    chinese_ratio       = _chinese_ratio(text)
    language_compliance = _detect_language(chinese_ratio)
    logger.info(f"[grader.grade] chinese_ratio={chinese_ratio:.2f} lang={language_compliance}")

    if chinese_ratio > 0.70:
        logger.info("[grader.grade] PATH=chinese_dominant")
        detail = _build_detail(
            "Missing", 0.0,
            {"A_ai_strategy": 0, "B_knowledge_restructuring": 0,
             "C_learning_material_value": 0, "D_personal_trace": 0},
            "chinese_dominant",
            "Submission is readable but does not meet the English-notes requirement.",
            request_status="skipped")
        return 0, (
            "Submission is readable, but it is written primarily in Chinese "
            "and does not meet the English-notes requirement. "
            "Grade: Missing. Please revise and resubmit in English-dominant form."
        ), True, detail

    # ── 建立 prompt ─────────────────────────────────────────────────
    user_prompt = SYSTEM_PROMPT
    if key_concepts.strip():
        user_prompt += (
            f"\n\n---\n## THIS WEEK'S KEY CONCEPTS\n"
            f"When assessing Dimension C, check whether these concepts appear:\n"
            f"{key_concepts.strip()}\n"
        )
    user_msg = f"Grade the following student notes:\n\n---\n{text[:8000]}\n---"

    # ── API 呼叫 ────────────────────────────────────────────────────
    last_error  = ""
    retry_count = 0

    for attempt in range(max_retries):
        retry_count = attempt
        try:
            client   = _get_client()
            response = client.models.generate_content(
                model=_model,
                contents=user_prompt + "\n\n" + user_msg,
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=800,
                    temperature=0.15,
                ),
            )
            raw = response.text.strip()
            break

        except Exception as e:
            last_error = str(e)
            err_lower  = last_error.lower()

            # 404 / model not found → 不重試
            if "404" in last_error or "not_found" in err_lower or "not found" in err_lower:
                detail = _build_detail(
                    "Average", 2.5,
                    {"A_ai_strategy": 2, "B_knowledge_restructuring": 2,
                     "C_learning_material_value": 2, "D_personal_trace": 2},
                    language_compliance, "",
                    request_status="invalid_model", retry_count=attempt)
                return 0, (
                    f"Model not found or invalid model configuration. "
                    f"Please check the model ID. ({last_error[:100]})"
                ), True, detail

            # 429 / quota → 不重試
            if "429" in last_error or "quota" in err_lower or "rate_limit" in err_lower:
                detail = _build_detail(
                    "Average", 2.5,
                    {"A_ai_strategy": 2, "B_knowledge_restructuring": 2,
                     "C_learning_material_value": 2, "D_personal_trace": 2},
                    language_compliance, "",
                    request_status="rate_limit", retry_count=attempt)
                return 0, (
                    f"Rate limit or quota exceeded. Manual review required. "
                    f"({last_error[:100]})"
                ), True, detail

            # 其他錯誤 → 指數退讓後重試
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 1))
        else:
            continue
        break
    else:
        detail = _build_detail(
            "Average", 2.5,
            {"A_ai_strategy": 2, "B_knowledge_restructuring": 2,
             "C_learning_material_value": 2, "D_personal_trace": 2},
            language_compliance, "",
            request_status="failed", retry_count=retry_count)
        return 0, (
            f"AI grading failed after {max_retries} attempts. ({last_error[:100]})"
        ), True, detail

    # ── 解析回應 ────────────────────────────────────────────────────
    grade_str, weighted, a, b, c, d, lang, brief_reason, model_needs_review = \
        _parse_response(raw)

    # 語言以本地計算為準
    lang = language_compliance

    # ── needs_review 觸發 ───────────────────────────────────────────
    needs_review = model_needs_review
    if lang in ("chinese_dominant", "mixed_chinese_heavy"):
        needs_review = True
    if 3.2 <= weighted <= 3.7 or 4.0 <= weighted <= 4.3:
        needs_review = True
    if max([a, b, c, d]) - min([a, b, c, d]) >= 3:
        needs_review = True
    if d == 1 and grade_str in ("Great", "Excellent", "Perfect"):
        needs_review = True

    # ── 輸出 ────────────────────────────────────────────────────────
    justification = _build_justification(grade_str, weighted, a, b, c, d, brief_reason)
    final_score   = GRADE_TO_SCORE.get(grade_str, 2)
    detail        = _build_detail(
                        grade_str, weighted,
                        {"A_ai_strategy": a, "B_knowledge_restructuring": b,
                         "C_learning_material_value": c, "D_personal_trace": d},
                        lang, brief_reason,
                        request_status="success", retry_count=retry_count)

    return final_score, justification, needs_review, detail


# ─────────────────────────────────────────────
# 向下相容包裝
# ─────────────────────────────────────────────
def grade_compat(text: str, model: str = FIXED_MODEL) -> Tuple[int, str, bool]:
    score, justification, needs_review, _ = grade(text)
    return score, justification, needs_review
