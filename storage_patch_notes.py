"""
storage_patch_notes.py
說明你需要在現有 storage.py 中做哪些改動
（這個檔案不需要上傳，只是給你看需要改什麼）

你的 storage.py 中，grades 欄位已有：
  ai_score, ai_justification, needs_review, language_compliance ...

需要確認以下欄位存在（若沒有就補上）：
  language_compliance       ← 今天已加，記得在 Sheets 手動補欄位標題
  ai_detail_grade           ← 新增：Excellent / Very Good / Good / Fair
  ai_detail_weighted        ← 新增：加權分數（如 3.8）
  ai_dim_a                  ← 新增：Prompt Strategy 分數 1–5
  ai_dim_b                  ← 新增：Knowledge Restructuring 分數 1–5
  ai_dim_c                  ← 新增：Learning Material Value 分數 1–5
  ai_dim_d                  ← 新增：Personal Trace 分數 1–5

如果你不想改 Sheets 欄位，最簡單的做法是：
  把這些維度分數都 pack 進 ai_justification 字串（grader.py 已這樣做）
  這樣不需要改任何 Sheets 欄位，只改 grader.py 就夠了。

────────────────────────────────────────────
app.py 中 record 建立的地方，需要從：

  score, justification, needs_review = grader.grade(text)

改為：

  score, justification, needs_review, detail = grader.grade(text)

  record = {
      ...
      "ai_score": score,
      "ai_justification": justification,
      "needs_review": needs_review,
      "language_compliance": detail.get("language_compliance", ""),
      # 以下是新增欄位（可選，若 Sheets 沒有這些欄位就跳過）
      # "ai_detail_grade": detail.get("grade", ""),
      # "ai_detail_weighted": detail.get("weighted_score", ""),
      ...
  }

────────────────────────────────────────────
admin_grading.py 中呼叫 grader 的地方，
如果還沒改，可以繼續用 grade_compat() 確保不破壞現有邏輯：

  from grader import grade_compat
  score, justification, needs_review = grade_compat(text)

等你確認新版運作正常，再換成完整的 grade()。
"""
