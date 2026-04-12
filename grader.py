"""
grader.py
AI 評分模組 — 使用 Gemini API 進行四維度加權評分
校正版本：2026-04，基於 7 份真實樣本校正

評分面向：
  A. AI Use Strategy / Prompt Quality     (25%)
  B. Knowledge Restructuring Quality      (30%)
  C. Learning Material Value              (25%)
  D. Personal Learning Trace              (20%)

等級對應：
  4.5–5.0 → Excellent
  3.5–4.4 → Very Good
  2.5–3.4 → Good
  1.0–2.4 → Fair
"""

import os
import re
import time
import json
import random
import logging
from datetime import datetime
from typing import Tuple

import google.genai as genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 模型設定（暫時固定，不開放切換）
# ─────────────────────────────────────────────
FIXED_MODEL   = "gemini-2.5-flash-lite"
DEFAULT_MODEL = FIXED_MODEL  # 向下相容，grade_compat() 等地方仍用此名稱

# ─────────────────────────────────────────────
# 系統 Prompt（校正版）
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """You are an academic grading assistant evaluating English study notes submitted by graduate students in an AI Classification course. The professor allows and encourages AI tool use. Your task is to assess how well the student used AI to create high-quality learning materials.

Evaluate the notes across FOUR dimensions. For each dimension, assign a score from 1 to 5. Then compute a weighted final score and map it to a final grade.

IMPORTANT: Use the FULL range of scores. Do NOT cluster scores at 3–4. A typical class should have a spread across Fair / Good / Very Good / Excellent. Be willing to give 1–2 for weak work and 5 for genuinely outstanding work.

---

## LANGUAGE RULE (apply before scoring)

This is an English-medium course. Notes must be primarily in English.

- English with occasional Chinese annotations, translations, or labels → ACCEPTABLE, score normally
- Clearly mixed (Chinese body text + English headings, or roughly half-half) → PENALISE: cap each dimension at 3 max, set language_compliance = "mixed"
- Primarily Chinese content (>60% Chinese body text) → FAIL: set all dimension scores to 1, final grade = "Fail", language_compliance = "chinese_dominant"
- Empty, unreadable, or scan-only → grade = "Missing", all scores = 0 (handled separately by system)

---

## DIMENSION A — AI Use Strategy / Prompt Quality (Weight: 25%)

Key question: Does the student show intentional, strategic use of AI — or just paste a generic request?

5 — Strategic and specific: prompt includes learner background OR specific source materials OR detailed output requirements. Shows the student thought about HOW to use AI for their own learning.
  Example signals: "I am an MBA student with no CS background…", lists multiple source types, specifies format/language/focus.

4 — Partially strategic: prompt has some specificity — a topic focus, a language requirement, or a learning context — but is missing one or two elements of full strategy.

3 — Functional but generic: a clear instruction is given (e.g. "summarise today's lecture on CNNs") but no background, no source specification, no learning strategy. The prompt could have been written by anyone.

2 — Vague or minimal: single-line generic instruction with no context (e.g. "help me organise these notes", "summarise this"). Almost no evidence of AI strategy.

1 — No visible prompt, or prompt is trivially short (under 10 words with no context). If no prompt is shown at all, default to 2 unless the notes themselves strongly suggest strategic AI use.

IMPORTANT DISTINCTION: A longer prompt is NOT automatically better. Score the quality of thinking, not the word count.

---

## DIMENSION B — Knowledge Restructuring Quality (Weight: 30%)

Key question: Has the student TRANSFORMED the material, or just reproduced it in a different layout?

Restructuring means: the student made deliberate choices about how to organise, reframe, or connect ideas — NOT just copying lecture structure.

Strong signals of restructuring:
- Question-driven section titles (e.g. "Why does CNN need deep stacking?" instead of "CNN deep stacking")
- Comparison tables that the student designed (not copied from slides)
- Thematic grouping that cuts across original lecture order
- Prerequisite/dependency maps or scaffolded frameworks
- Student-coined labels or mnemonics for concepts

Weak or absent restructuring:
- Section titles match lecture slides exactly
- Content is bullet-pointed but follows the same order as the source
- "Restructuring" is only cosmetic (added bold/headers but same content flow)

5 — Multiple strong restructuring techniques applied coherently throughout. The notes clearly reflect the student's own conceptual map of the topic.

4 — At least one strong restructuring technique applied meaningfully (e.g. a well-designed comparison table OR question-driven chapters). The notes feel organised by the student's understanding, not the source order.

3 — Some structure beyond plain summarisation, but at least half the content still follows source order or feels like compressed copying. One weak restructuring attempt present.

2 — Primarily summary or transcription. Minor reorganisation (e.g. added headings) but no real transformation of the material.

1 — Pure transcription or bullet-point copying with no restructuring whatsoever. Could have been generated by "summarise this verbatim."

---

## DIMENSION C — Learning Material Value (Weight: 25%)

Key question: If a classmate borrowed this, would it actually help them understand and revise the topic?

5 — Excellent standalone study tool: comprehensive, well-structured, appropriate density. Includes at least one feature that aids quick review (e.g. summary table, glossary, workflow diagram, key-term list). Immediately usable for an exam or presentation.

4 — Good study material: covers the main concepts clearly, logical structure, readable. A classmate could use it to review. Missing one or two important concepts or lacks quick-reference features.

3 — Adequate but incomplete: covers some key concepts but has noticeable gaps, OR is hard to follow in places, OR is so brief that a classmate would still need the original slides.

2 — Limited value: either too short (under ~300 words for a full lecture), too surface-level, or missing multiple important concepts. A classmate would get little benefit from borrowing this.

1 — Very low value: the notes would not help anyone understand the topic. Mostly filler, off-topic, or a single paragraph for a multi-hour lecture.

---

## DIMENSION D — Personal Learning Trace (Weight: 20%)

Key question: Is there evidence that THIS student processed this material — or could anyone have produced this?

Personal trace is NOT limited to first-person paragraphs. It includes ANY of:
- First-person observations, questions, or connections (even brief: "I found this confusing because…")
- Student-invented labels or mnemonics (e.g. "Triple BAM Rule", "Fanciness Fallacy")
- Explicit connections to the student's own field, job, or prior experience
- Prompt design that reveals personal learning needs (e.g. "I am an MBA student with no CS background")
- Section design choices that reflect personal priorities (e.g. spending more space on a concept the student found hard)

5 — Clear, pervasive personal trace in multiple forms. The notes are unmistakably this student's own learning journey.

4 — At least one genuine personal trace element that is specific and non-generic (e.g. a real field connection, a coined label, a personal question). Not just a boilerplate reflection paragraph.

3 — Minimal but present: a generic reflection section ("I learned a lot from this lecture") OR the prompt mentions learner background but the notes themselves have no personal voice.

2 — Almost no trace. The notes could have been written by any student in any class. No personal connections, no personal framing.

1 — Zero personal trace. Entirely generic. No reflection, no personal framing, no individual voice anywhere.

IMPORTANT: High restructuring (B=5) does NOT automatically mean high personal trace (D=5). Score them independently. A beautifully organised set of notes can still have no personal voice.

---

## SCORING LOGIC

Compute weighted score:
  weighted_score = (A × 0.25) + (B × 0.30) + (C × 0.25) + (D × 0.20)

Map to grade using STRICT boundaries — do not round up:
  4.5–5.0 → Excellent  (genuinely outstanding work, rare)
  3.5–4.4 → Very Good  (clearly above average, but not perfect)
  2.5–3.4 → Good       (meets requirements, average quality)
  1.5–2.4 → Fair       (below average, passes minimally)
  0.5–1.4 → Fail       (does not meet course requirements)
  0.0–0.4 → Missing    (empty or unreadable)

CALIBRATION GUIDANCE — to prevent score clustering:
- "Good" (3) means average, not praise. Most adequate-but-unremarkable notes should land here.
- "Very Good" (4) requires clear evidence of quality ABOVE average in at least 2 dimensions.
- "Excellent" (5) should be rare. Only notes that are genuinely impressive across most dimensions.
- "Fair" (2) is appropriate for notes that are weak but show some effort — not just for failures.
- Do NOT give 4 to notes that are merely "complete" or "well-formatted" without genuine restructuring or learning value.

LANGUAGE PENALTY (applied before grade mapping):
- If language_compliance = "mixed": cap weighted_score at 3.4 (maximum grade = Good)
- If language_compliance = "chinese_dominant": override grade to "Fail", set final_score = 1

---

## OUTPUT FORMAT

Return ONLY a valid JSON object. No preamble, no markdown, no explanation outside the JSON.

{
  "dimension_scores": {
    "A_ai_strategy": <1-5>,
    "B_knowledge_restructuring": <1-5>,
    "C_learning_material_value": <1-5>,
    "D_personal_trace": <1-5>
  },
  "weighted_score": <float, 1 decimal place>,
  "grade": "<Excellent | Very Good | Good | Fair | Fail | Missing>",
  "language_compliance": "<chinese_dominant | mixed | english_compliant>",
  "needs_review": <true | false>,
  "brief_reason": "<ONE sentence only: name the single strongest point and the single most important weakness. Max 25 words.>"
}

Set needs_review = true ONLY when:
- language_compliance is chinese_dominant or mixed
- any dimension score is 1 (something is seriously wrong)
- weighted_score is exactly on a grade boundary (3.4–3.6 or 4.4–4.6)
- you are genuinely uncertain about the grade (not just because the work is average)

Do NOT set needs_review = true for normal Good or Very Good work.
"""

# ─────────────────────────────────────────────
# 等級對應（顯示用）
# ─────────────────────────────────────────────
GRADE_TO_DISPLAY = {
    "Excellent":  {"label": "Excellent",  "emoji": "🌟", "color": "gold"},
    "Very Good":  {"label": "Very Good",  "emoji": "✅", "color": "green"},
    "Good":       {"label": "Good",       "emoji": "👍", "color": "blue"},
    "Fair":       {"label": "Fair",       "emoji": "⚠️", "color": "orange"},
}

# weighted_score → 舊版 final_score 對應（與 Google Sheets 相容）
GRADE_TO_SCORE = {
    "Excellent": 5,
    "Very Good": 4,
    "Good":      3,
    "Fair":      2,
    "Fail":      1,
    "Missing":   0,
}


# ─────────────────────────────────────────────
# 主要評分函式
# ─────────────────────────────────────────────
def grade(
    text: str,
    key_concepts: str = "",
    max_retries: int = 3,
) -> Tuple[int, str, bool, dict]:
    """
    對筆記文字進行 AI 評分。
    模型固定為 FIXED_MODEL（gemini-2.5-flash-lite），不接受外部傳入。

    Returns:
        (final_score, justification, needs_review, log)

        final_score : int，0 = 失敗未完成評分，2–5 = 正常結果
        log dict 固定包含：
          model_name, graded_at, retry_count,
          request_status, input_tokens_est, language_compliance
        request_status 值：success / rate_limit / parse_error / failed / skipped
    """
    model = FIXED_MODEL
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _base_log(model_name, graded_at, retry_count, status, tokens, lang):
        return {
            "model_name":          model_name,
            "graded_at":           graded_at,
            "retry_count":         retry_count,
            "request_status":      status,
            "input_tokens_est":    tokens,
            "language_compliance": lang,
        }

    def _fail(score, justification, needs_review, status,
              model_name=model, retry_count=0, tokens=0, lang=""):
        return score, justification, needs_review, _base_log(
            model_name, "", retry_count, status, tokens, lang)

    # ── 空內容 ──────────────────────────────────
    if not text or len(text.strip()) < 10:
        return _fail(0, "Submission is empty or unreadable.", False, "skipped")

    # ── 語言預檢 ────────────────────────────────
    chinese_ratio       = _chinese_ratio(text)
    language_compliance = _detect_language(chinese_ratio)

    # 純中文直接給 Fair，不呼叫 API
    if chinese_ratio > 0.70:
        log = _base_log(model, _now(), 0, "success", len(text[:8000]), "chinese_dominant")
        log.update({
            "grade": "Fair", "weighted_score": 2.0,
            "dimension_scores": {
                "A_ai_strategy": 1, "B_knowledge_restructuring": 1,
                "C_learning_material_value": 1, "D_personal_trace": 1,
            },
        })
        return 2, "The notes are primarily written in Chinese. English notes are required.", True, log

    # ── 截斷 ────────────────────────────────────
    sample_text      = text[:8000]
    input_tokens_est = len(sample_text) // 2

    # ── Gemini API 呼叫 ──────────────────────────
    retry_count = 0
    for attempt in range(max_retries):
        retry_count = attempt
        try:
            client     = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
            used_model = FIXED_MODEL

            prompt = f"Please grade the following student English notes:\n\n---\n{sample_text}\n---"
            if key_concepts:
                prompt += f"\n\nKey concepts for this week: {key_concepts}"

            response = client.models.generate_content(
                model=used_model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=2048,
                    temperature=0.1,
                ),
            )
            raw = response.text.strip()
            score, justification, needs_review, detail = _parse_response(raw, language_compliance)

            # 用 _base_log 建立固定欄位，但依 parse 結果決定 request_status
            parse_status = detail.get("request_status", "parse_error")
            log = _base_log(
                used_model, _now(), retry_count,
                parse_status,          # 若 parse 失敗用 parse_error，成功用 success
                input_tokens_est, language_compliance,
            )
            # 合併 detail（評分內容），但不讓 detail 覆蓋 model_name / graded_at
            for k, v in detail.items():
                if k not in ("model_name", "graded_at", "retry_count",
                             "request_status", "input_tokens_est", "language_compliance"):
                    log[k] = v
            return score, justification, needs_review, log

        except Exception as e:
            err_str = str(e)
            logger.warning(f"Gemini API attempt {attempt + 1} failed: {err_str[:120]}")

            # 429：立即中止，不再 retry
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                return _fail(
                    0,
                    "Rate limit reached (429). Please wait 1 minute and try again. / "
                    "已達API速率上限，請等待1分鐘後再試。",
                    True, "rate_limit",
                    model_name=used_model,
                    retry_count=retry_count,
                    tokens=input_tokens_est,
                    lang=language_compliance,
                )

            if attempt < max_retries - 1:
                wait = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)

    # ── 所有 retry 耗盡 ─────────────────────────
    return _fail(
        0,
        "AI grading failed after multiple attempts. Manual review required.",
        True, "failed",
        retry_count=retry_count,
        tokens=input_tokens_est,
        lang=language_compliance,
    )


# ─────────────────────────────────────────────
# 內部工具函式
# ─────────────────────────────────────────────
def _parse_response(raw: str, language_compliance: str) -> Tuple[int, str, bool, dict]:
    """解析 Gemini 回傳的 JSON。
    flash 系列模型有時在 JSON 前後加說明文字或 code fence，加強清理邏輯。
    """
    try:
        # 1. 移除 markdown code fence（含前後換行）
        cleaned = re.sub(r"```json\s*|\s*```", "", raw).strip()
        # 2. 找第一個 { 到最後一個 } 之間的內容（處理前後有說明文字的情況）
        start = cleaned.find("{")
        end   = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end+1]
        data = json.loads(cleaned)

        dim = data.get("dimension_scores", {})
        a = max(1, min(5, int(dim.get("A_ai_strategy", 2))))
        b = max(1, min(5, int(dim.get("B_knowledge_restructuring", 2))))
        c = max(1, min(5, int(dim.get("C_learning_material_value", 2))))
        d = max(1, min(5, int(dim.get("D_personal_trace", 2))))

        weighted = round(a * 0.25 + b * 0.30 + c * 0.25 + d * 0.20, 1)

        # 等級判斷
        grade_str = _score_to_grade(weighted)

        # Soft ceiling 規則
        soft_ceiling = False
        if d == 1 and b <= 2:
            soft_ceiling = True
            if grade_str in ("Very Good", "Excellent"):
                grade_str = "Good"

        # 覆蓋 Gemini 自己判斷的 grade（以我們計算為準）
        lang         = data.get("language_compliance", language_compliance)
        needs_review = bool(data.get("needs_review", False))

        # ── 語言懲罰（程式層保底，不依賴模型自己執行）──────
        if lang == "chinese_dominant":
            grade_str = "Fail"
            weighted  = min(weighted, 1.4)
        elif lang == "mixed":
            weighted  = min(weighted, 3.4)
            if grade_str in ("Very Good", "Excellent"):
                grade_str = "Good"

        # ── needs_review：只在真正需要時觸發 ──────────────
        # 語言問題
        if lang in ("chinese_dominant", "mixed"):
            needs_review = True
        # 某維度極低（值得老師特別看）
        if min(a, b, c, d) == 1:
            needs_review = True
        # 分數恰好在等級邊界
        if 3.4 <= weighted <= 3.6 or 4.4 <= weighted <= 4.6:
            needs_review = True
        # 不再因為「一般 Good/Very Good 正常作業」觸發 needs_review

        # 組合評語
        brief_reason  = str(data.get("brief_reason", "")).strip()[:150]  # 硬性截斷保險
        justification = _build_justification(grade_str, weighted, a, b, c, d, brief_reason)

        final_score = GRADE_TO_SCORE.get(grade_str, 2)
        detail = {
            "grade":          grade_str,
            "weighted_score": weighted,
            "dimension_scores": {
                "A_ai_strategy":            a,
                "B_knowledge_restructuring": b,
                "C_learning_material_value": c,
                "D_personal_trace":          d,
            },
            "language_compliance": lang,
            "request_status":      "success",
        }

        return final_score, justification, needs_review, detail

    except Exception as ex:
        logger.error(f"Parse error: {ex} | raw: {raw[:1000]}")
        return (
            0,
            "Could not parse AI response. Manual review required.",
            True,
            {
                "model_name":          "",
                "graded_at":           "",
                "retry_count":         0,
                "request_status":      "parse_error",
                "input_tokens_est":    0,
                "language_compliance": language_compliance,
            },
        )


def _score_to_grade(weighted: float) -> str:
    if weighted >= 4.5:
        return "Excellent"
    elif weighted >= 3.5:
        return "Very Good"
    elif weighted >= 2.5:
        return "Good"
    elif weighted >= 1.5:
        return "Fair"
    elif weighted >= 0.5:
        return "Fail"
    else:
        return "Missing"


def _build_justification(grade_str, weighted, a, b, c, d, brief_reason: str = "") -> str:
    lines = [
        f"Grade: {grade_str} (Weighted Score: {weighted}/5.0)",
        f"A-Prompt Strategy: {a}/5 | B-Knowledge Restructuring: {b}/5 | "
        f"C-Learning Value: {c}/5 | D-Personal Trace: {d}/5",
    ]
    if brief_reason:
        lines.append(brief_reason)
    return " | ".join(lines)


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
        return "mixed"
    else:
        return "english_compliant"


# ─────────────────────────────────────────────
# 向下相容包裝（舊版 admin_grading.py 呼叫用）
# ─────────────────────────────────────────────
def grade_compat(text: str) -> Tuple[int, str, bool]:
    """
    舊版相容介面：只回傳 (score, justification, needs_review)
    給尚未更新的 admin_grading.py 使用。
    """
    score, justification, needs_review, _ = grade(text)
    return score, justification, needs_review
