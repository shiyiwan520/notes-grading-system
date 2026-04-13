"""
grader.py
AI 評分模組 — 使用 Gemini API 進行四維度加權評分

評分面向：
  A. AI Use Strategy / Prompt Quality     (25%)
  B. Knowledge Restructuring Quality      (30%)
  C. Learning Material Value              (25%)
  D. Personal Learning Trace              (20%)

整體等級（7 級制）：
  Perfect / Excellent / Great / Good / Average / Fair / Poor / Missing

Missing = 獨立狀態，用於空白 / unreadable / scan-only / 純中文

─────────────────────────────────────────────
Changelog
─────────────────────────────────────────────
v3.3  2026-04-13  Migrate from google-generativeai to google-genai SDK
  - import: google.generativeai → from google import genai + genai_types
  - _get_model() → _get_client() using genai.Client(api_key=...)
  - generate_content call updated to client.models.generate_content()
  - Fixes ImportError on Streamlit Cloud (old SDK end-of-support)
  - No changes to rubric, grade thresholds, or language rules


  - chinese_dominant (>70%) → Missing, score=0 (unchanged)
  - Updated justification to clearly state submission is readable but
    does not meet English-notes requirement; added resubmit instruction
  - Distinguishes from empty/unreadable path (separate len<10 branch)
  - No changes to rubric, grade thresholds, or other modules

v3.1  2026-04-13  Chinese-dominant reclassified from Poor → Missing
  - chinese_dominant now returns score=0 / grade=Missing (was Poor/1)
  - Added distinct justification messages for empty vs Chinese-dominant
  - No changes to rubric or grade thresholds

v3.0  2026-04-13  7-level grade system + rubric calibration
  - Grade labels: Perfect/Excellent/Great/Good/Average/Fair/Poor/Missing
  - Replaced 6-level (Excellent/Very Good/Good/Fair) system
  - New grade boundaries: Perfect≥4.7, Excellent≥4.1, Great≥3.5,
    Good≥2.9, Average≥2.2, Fair≥1.5, Poor≥1.0
  - B dimension rubric: explicit list of what does NOT count as
    high-quality restructuring (summary ≠ transformation)
  - Added calibration reminders in system prompt to prevent over-scoring
  - needs_review triggers tightened: boundary scores, dim variance,
    language issues, D=1 with high grade
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
# 模型設定
# ─────────────────────────────────────────────
DEFAULT_MODEL = "gemini-2.5-flash-lite-preview-06-17"
FALLBACK_MODEL = "gemini-2.5-flash"

# ─────────────────────────────────────────────
# 等級 → 舊版數字分數對應（與 Google Sheets / Supabase 相容）
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

# ─────────────────────────────────────────────
# weighted score → 整體等級對應（7 級制）
# ─────────────────────────────────────────────
def _score_to_grade(weighted: float) -> str:
    if weighted >= 4.7:
        return "Perfect"
    elif weighted >= 4.1:
        return "Excellent"
    elif weighted >= 3.5:
        return "Great"
    elif weighted >= 2.9:
        return "Good"
    elif weighted >= 2.2:
        return "Average"
    elif weighted >= 1.5:
        return "Fair"
    else:
        return "Poor"

# ─────────────────────────────────────────────
# 系統 Prompt（7 級制校正版）
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """You are an academic grading assistant evaluating English study notes submitted by graduate students in an AI Classification course. The professor allows and encourages AI tool use. Your task is to assess how well the student used AI to create high-quality learning materials.

Evaluate the notes across FOUR dimensions. For each dimension, assign a score from 1 to 5. Then compute a weighted final score.

---

## DIMENSION A — AI Use Strategy / Prompt Quality (Weight: 25%)

Look for: Is the prompt included in the notes? If yes, assess its quality.

5 — Highly strategic: clear learner background, specific source materials listed (e.g. slides, transcript, external references), detailed output requirements, explicit learning goals. Demonstrates intentional AI collaboration.
4 — Partially strategic: specifies a learning focus, format constraints, or personal context, but not all elements are present.
3 — Functional but generic: clear task instructions but lacks learner background, source listing, or strategic framing. E.g. "Summarize the lecture with clear sections."
2 — Vague: generic one-line instruction with no strategy (e.g. "summarize the lecture / 整理筆記").
1 — No prompt shown, or a single very short instruction with no context whatsoever.

If no prompt is visible, default to score 2 unless strong indirect evidence of AI strategy exists in the notes themselves.

---

## DIMENSION B — Knowledge Restructuring Quality (Weight: 30%)

This is the most important dimension. It distinguishes genuine transformation from surface-level tidying.

### What does NOT count as high-quality restructuring:
- Renaming slide headings into note headings
- Bullet-point listing of definitions
- Summary rewriting with minor paraphrasing
- Presenting content in the same order as the original source

### What counts as GENUINE restructuring (needed for score 4–5):
- Question-driven section design (e.g. "Why does overfitting happen?" as a chapter heading)
- Concept comparison tables built by the student (e.g. Bias vs Variance side-by-side)
- Cross-source integration (merging lecture slides + external video + own notes into one framework)
- Student-invented logical frameworks or mnemonics that reorganize the material
- Synthesis of multiple concepts into a new unified model

Scoring guide:
5 — Multiple forms of genuine restructuring throughout; student clearly imposed their own logic on the material
4 — At least one clear, genuine restructuring technique beyond summarization
3 — Mostly summarized, but with minor structural choices (e.g. a comparison table, or a question-led section)
2 — Well-organized summary: logical flow, clear headings, but content order follows the source material
1 — Bullet-point dump or near-verbatim copy with minimal structure

CRITICAL: Do NOT raise B above 3 for notes that are "well-organized summaries." Organization ≠ restructuring. A note that covers all lecture points clearly and neatly is a score 2–3, not a 4–5.

---

## DIMENSION C — Learning Material Value (Weight: 25%)

Evaluate whether these notes would be genuinely useful to study from.

5 — Comprehensive coverage, key formulas/examples included, would be fully sufficient as a standalone study resource
4 — Covers most key concepts well, minor gaps, useful for study
3 — Covers the main topics but lacks depth or misses important details; adequate but not ideal
2 — Partial coverage, missing multiple key points, or too shallow to be reliable
1 — Very thin content, major gaps, would not be useful for studying

---

## DIMENSION D — Personal Learning Trace (Weight: 20%)

Look for evidence that a real student's learning process shaped this document.

Accept ANY of:
- First-person observations, doubts, or connections in the text
- Personal naming conventions or student-invented mnemonics (e.g. "Triple BAM Rule")
- Connection to the student's own field, profession, or prior knowledge
- Prompt design that reveals personal learning needs or background
- Section design choices that clearly reflect the student's own learning priorities

5 — Pervasive personal trace: multiple forms present throughout, clearly the student's own learning journey
4 — Meaningful personal trace: at least one form clearly present and genuine
3 — Superficial trace: a generic reflection section exists, OR minor personal framing appears in one place
2 — Minimal trace: barely any evidence the student personalized this material
1 — No trace: entirely generic, could have been written by anyone, no personal voice or connection anywhere

---

## SCORING LOGIC

Compute the weighted score:
  weighted_score = (A × 0.25) + (B × 0.30) + (C × 0.25) + (D × 0.20)
  Round to 1 decimal place.

Map to overall grade using these boundaries:
  4.7–5.0 → Perfect    (extremely rare; all dimensions near 5, genuine excellence)
  4.1–4.6 → Excellent  (very strong across all dimensions)
  3.5–4.0 → Great      (clearly above average; at least one dimension outstanding)
  2.9–3.4 → Good       (meets requirements; competent but not outstanding)
  2.2–2.8 → Average    (passable; no major failures but no real strength)
  1.5–2.1 → Fair       (below average; clear weaknesses)
  1.0–1.4 → Poor       (does not meet requirements; barely readable)

SOFT CEILING RULE:
  Apply ONLY when ALL THREE conditions are true:
  - D = 1 (zero personal trace)
  - B ≤ 2 (pure summary / bullet dump, no restructuring)
  - C ≤ 3 (coverage not outstanding)
  In this case, cap the grade at "Good" regardless of weighted score.
  Do NOT apply this ceiling when any one of these conditions is absent.

CALIBRATION REMINDERS (to prevent known AI biases):
  - A well-organized, complete summary is typically Average to Good. It should NOT reach Great or Excellent.
  - Great requires B ≥ 4 OR a combination of A ≥ 4 and D ≥ 4 with B ≥ 3.
  - Excellent requires B ≥ 4 AND D ≥ 3 AND A ≥ 3.
  - Perfect requires B = 5 AND (D ≥ 4 OR A = 5) AND C ≥ 4.
  - A visually polished document with a detailed prompt but only summary-level content should NOT exceed Good.

---

## LANGUAGE COMPLIANCE

After scoring, assess the language of the submission:
- english_compliant: >70% English text (normal; occasional Chinese annotations are fine and should NOT reduce scores)
- mixed_chinese_heavy: Chinese text is clearly dominant but some English present (>30% Chinese)
- chinese_dominant: >70% Chinese text (main content in Chinese)

Chinese annotations, bilingual vocabulary labels, or occasional Chinese comments within an otherwise English document → treat as english_compliant.

---

## OUTPUT FORMAT

Return ONLY a valid JSON object. No preamble, no markdown fences, no explanation outside the JSON.

{
  "dimension_scores": {
    "A_ai_strategy": <1-5>,
    "B_knowledge_restructuring": <1-5>,
    "C_learning_material_value": <1-5>,
    "D_personal_trace": <1-5>
  },
  "weighted_score": <float, 1 decimal place>,
  "grade": "<Perfect | Excellent | Great | Good | Average | Fair | Poor>",
  "soft_ceiling_applied": <true | false>,
  "language_compliance": "<english_compliant | mixed_chinese_heavy | chinese_dominant>",
  "key_evidence": {
    "A_evidence": "<1-2 sentences citing specific prompt features or their absence>",
    "B_evidence": "<1-2 sentences describing the restructuring quality — be specific about what techniques were or were not used>",
    "C_evidence": "<1-2 sentences on coverage and usability>",
    "D_evidence": "<1-2 sentences citing specific personal trace evidence or its absence>"
  },
  "needs_review": <true | false>,
  "needs_review_reason": "<brief reason if needs_review is true, else null>"
}
"""

# ─────────────────────────────────────────────
# 內部工具函式
# ─────────────────────────────────────────────
def _chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_chars = len([c for c in text if c.strip()])
    return chinese_chars / total_chars if total_chars > 0 else 0.0


def _detect_language(ratio: float) -> str:
    if ratio > 0.70:
        return "chinese_dominant"
    elif ratio > 0.30:
        return "mixed_chinese_heavy"
    else:
        return "english_compliant"


def _get_client():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    return genai.Client(api_key=api_key)


def _build_justification(grade_str: str, weighted: float,
                          a: int, b: int, c: int, d: int,
                          evidence: dict) -> str:
    parts = [
        f"Grade: {grade_str} (Weighted Score: {weighted}/5.0)",
        f"A-Prompt: {a}/5 | B-Restructuring: {b}/5 | C-Value: {c}/5 | D-Personal: {d}/5",
    ]
    if evidence.get("B_evidence"):
        parts.append(f"Restructuring: {evidence['B_evidence']}")
    if evidence.get("D_evidence"):
        parts.append(f"Personal trace: {evidence['D_evidence']}")
    return " | ".join(parts)[:700]


def _build_detail(grade_str, weighted, dim_scores, lang, soft_ceiling, evidence) -> dict:
    return {
        "grade": grade_str,
        "weighted_score": weighted,
        "dimension_scores": dim_scores,
        "language_compliance": lang,
        "soft_ceiling_applied": soft_ceiling,
        "key_evidence": evidence,
    }


def _parse_response(raw: str):
    """Parse Gemini JSON response. Returns (grade_str, weighted, a, b, c, d, lang, soft, evidence, needs_review)."""
    grade_str = "Average"
    weighted  = 2.5
    a = b = c = d = 2
    lang      = "english_compliant"
    soft      = False
    evidence  = {}
    needs_review = False

    try:
        cleaned = re.sub(r"```json|```", "", raw).strip()
        data    = json.loads(cleaned)

        dims    = data.get("dimension_scores", {})
        a = int(dims.get("A_ai_strategy", 2))
        b = int(dims.get("B_knowledge_restructuring", 2))
        c = int(dims.get("C_learning_material_value", 2))
        d = int(dims.get("D_personal_trace", 2))

        weighted    = round(float(data.get("weighted_score", a*0.25 + b*0.30 + c*0.25 + d*0.20)), 1)
        grade_str   = data.get("grade", _score_to_grade(weighted))
        soft        = bool(data.get("soft_ceiling_applied", False))
        lang        = data.get("language_compliance", "english_compliant")
        evidence    = data.get("key_evidence", {})
        needs_review = bool(data.get("needs_review", False))
    except Exception:
        # Fallback: regex parse
        try:
            m = re.search(r'"weighted_score"\s*:\s*([\d.]+)', raw)
            if m:
                weighted  = round(float(m.group(1)), 1)
                grade_str = _score_to_grade(weighted)
            for key, var in [("A_ai_strategy", "a"), ("B_knowledge_restructuring", "b"),
                              ("C_learning_material_value", "c"), ("D_personal_trace", "d")]:
                mm = re.search(rf'"{key}"\s*:\s*(\d)', raw)
                if mm:
                    locals()[var]  # just touch to avoid linter complaint
            needs_review = True
        except Exception:
            pass

    return grade_str, weighted, a, b, c, d, lang, soft, evidence, needs_review


# ─────────────────────────────────────────────
# 主要評分函式
# ─────────────────────────────────────────────
def grade(
    text: str,
    key_concepts: str = "",
    model: str = DEFAULT_MODEL,
    max_retries: int = 3,
) -> Tuple[int, str, bool, dict]:
    """
    對筆記文字進行 AI 評分。

    Returns:
        (final_score, justification, needs_review, detail_dict)

        final_score   : int  0–5（與舊版 Google Sheets 欄位相容）
        justification : str  英文評語（含四維度摘要）
        needs_review  : bool
        detail_dict   : {
            "grade": str,            # 7-level: Perfect/Excellent/Great/Good/Average/Fair/Poor/Missing
            "weighted_score": float,
            "dimension_scores": dict,
            "language_compliance": str,
            "soft_ceiling_applied": bool,
            "key_evidence": dict,
        }
    """
    # ── 空內容 ───────────────────────────────────────────────────────
    if not text or len(text.strip()) < 10:
        detail = _build_detail("Missing", 0.0,
            {"A_ai_strategy": 0, "B_knowledge_restructuring": 0,
             "C_learning_material_value": 0, "D_personal_trace": 0},
            "unknown", False,
            {"A_evidence": "Submission is empty or unreadable.",
             "B_evidence": "", "C_evidence": "", "D_evidence": ""})
        return 0, "Submission is empty, unreadable, or scan-only. Grade: Missing.", True, detail

    # ── 語言預檢 ─────────────────────────────────────────────────────
    chinese_ratio       = _chinese_ratio(text)
    language_compliance = _detect_language(chinese_ratio)

    # 純中文（>70%）→ Missing（可讀但不符合英文筆記要求，不是 empty/unreadable）
    if chinese_ratio > 0.70:
        detail = _build_detail("Missing", 0.0,
            {"A_ai_strategy": 0, "B_knowledge_restructuring": 0,
             "C_learning_material_value": 0, "D_personal_trace": 0},
            "chinese_dominant", False,
            {"A_evidence": "Notes are primarily in Chinese; course requires English notes.",
             "B_evidence": "Cannot assess English restructuring quality.",
             "C_evidence": "Notes do not meet the English language requirement.",
             "D_evidence": "Cannot assess personal trace in Chinese-dominant notes."})
        return 0, (
            "Submission is readable, but it is written primarily in Chinese "
            "and does not meet the English-notes requirement. "
            "Grade: Missing. Please revise and resubmit in English-dominant form."
        ), True, detail

    # ── 建立 prompt ──────────────────────────────────────────────────
    user_prompt = SYSTEM_PROMPT
    if key_concepts.strip():
        user_prompt += (
            f"\n\n---\n## THIS WEEK'S KEY CONCEPTS\n"
            f"When assessing Dimension C (Learning Material Value), specifically check whether "
            f"the following concepts appear in the student's notes:\n{key_concepts.strip()}\n"
        )

    sample_text = text[:8000]
    user_msg    = f"Grade the following student notes:\n\n---\n{sample_text}\n---"

    # ── API 呼叫（含 retry） ──────────────────────────────────────────
    last_error  = ""
    retry_count = 0

    for attempt in range(max_retries):
        retry_count = attempt
        try:
            client   = _get_client()
            response = client.models.generate_content(
                model=model,
                contents=user_prompt + "\n\n" + user_msg,
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=1200,
                    temperature=0.15,
                ),
            )
            raw = response.text.strip()
            break

        except Exception as e:
            last_error = str(e)
            err_lower  = last_error.lower()

            # 429 / quota → 不重試
            if "429" in last_error or "quota" in err_lower or "rate" in err_lower:
                detail = _build_detail("Average", 2.5,
                    {"A_ai_strategy": 2, "B_knowledge_restructuring": 2,
                     "C_learning_material_value": 2, "D_personal_trace": 2},
                    language_compliance, False, {})
                return 0, f"Rate limit reached. Manual review required. ({last_error[:80]})", True, detail

            # 其他錯誤 → 指數退讓
            if attempt < max_retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)
        else:
            continue
        break
    else:
        detail = _build_detail("Average", 2.5,
            {"A_ai_strategy": 2, "B_knowledge_restructuring": 2,
             "C_learning_material_value": 2, "D_personal_trace": 2},
            language_compliance, False, {})
        return 0, f"AI grading failed after {max_retries} attempts. ({last_error[:80]})", True, detail

    # ── 解析回應 ─────────────────────────────────────────────────────
    grade_str, weighted, a, b, c, d, lang, soft, evidence, model_needs_review = _parse_response(raw)

    # 語言合規覆蓋（以本地計算為準）
    lang = language_compliance

    # Mixed Chinese heavy → 允許 Fair 上限一級
    # 這裡不強制 override grade，只確保 needs_review = True
    mixed_penalty_applied = (lang == "mixed_chinese_heavy")

    # ── needs_review 觸發條件 ────────────────────────────────────────
    needs_review = model_needs_review

    # 1. 語言問題
    if lang in ("chinese_dominant", "mixed_chinese_heavy"):
        needs_review = True

    # 2. 邊界分數（模型不確定）
    if 3.2 <= weighted <= 3.7 or 4.0 <= weighted <= 4.3:
        needs_review = True

    # 3. 維度極端差異（某維度特別低）
    scores_list = [a, b, c, d]
    if max(scores_list) - min(scores_list) >= 3:
        needs_review = True

    # 4. D = 1 且整體給到 Great 以上（可疑）
    if d == 1 and grade_str in ("Great", "Excellent", "Perfect"):
        needs_review = True

    # ── 組合輸出 ─────────────────────────────────────────────────────
    justification = _build_justification(grade_str, weighted, a, b, c, d, evidence)
    final_score   = GRADE_TO_SCORE.get(grade_str, 2)

    detail = _build_detail(grade_str, weighted,
        {"A_ai_strategy": a, "B_knowledge_restructuring": b,
         "C_learning_material_value": c, "D_personal_trace": d},
        lang, soft, evidence)
    detail["request_status"]        = "success"
    detail["retry_count"]           = retry_count
    detail["mixed_penalty_applied"] = mixed_penalty_applied

    return final_score, justification, needs_review, detail


# ─────────────────────────────────────────────
# 向下相容包裝（舊版呼叫介面）
# ─────────────────────────────────────────────
def grade_compat(text: str, model: str = DEFAULT_MODEL) -> Tuple[int, str, bool]:
    """
    舊版相容介面：只回傳 (score, justification, needs_review)
    給尚未更新到 4-tuple 的 admin_grading.py 使用。
    """
    score, justification, needs_review, _ = grade(text, model=model)
    return score, justification, needs_review
