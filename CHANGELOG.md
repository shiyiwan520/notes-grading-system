# Changelog — Notes Grading System

每次開新對話視窗，請把這個檔案連同你要修改的程式一起傳給 AI，
讓 AI 能快速掌握目前進度，避免拿舊版程式來改。

---

## 目前系統架構（2026-04-13）

| 層次 | 技術 |
|---|---|
| Frontend | Streamlit |
| AI 評分 | Gemini API（`google-genai` 新版 SDK） |
| 資料庫 | Supabase Database（已從 Google Sheets 完全遷移） |
| PDF 儲存 | Supabase Storage（bucket: `notes-pdf`） |
| 部署 | Streamlit Cloud |

**主要檔案：**
- `app.py` — 主應用程式（學生繳交 + 自動評分）
- `grader.py` — AI 評分模組（Gemini，4 維度，7 級制）
- `admin_grading.py` — 老師後台批改頁面
- `storage.py` — 資料存取層（Supabase）
- `db.py` — Supabase 底層操作
- `requirements.txt` — 套件清單

---

## v4.1 — 2026-04-13

**檔案：`admin_grading.py`**

- 移除兩處 `active_model = grader.get_active_model()`
- 移除兩處 `model=active_model` 參數（`grader.grade()` 呼叫）
- 兩處 `"ai_model": active_model` → `"ai_model": grader.FIXED_MODEL`
- `app.py` 已經乾淨，不需要修改

```
fix: remove all grader.get_active_model() calls from admin_grading.py
```

---

## v4.0 — 2026-04-13

**檔案：`grader.py`（完整重寫）**

- `FIXED_MODEL = "gemini-2.5-flash-lite"`，移除所有 model switching 邏輯
- 移除：`FALLBACK_MODEL`、`get_active_model()`、model whitelist、preview model 名稱
- JSON 輸出改為短版：`dimension_scores`, `weighted_score`, `grade`, `language_compliance`, `needs_review`, `brief_reason`（移除 `key_evidence`）
- `max_output_tokens` 從 1200 降為 800
- 錯誤分類修正：404/NOT_FOUND → `invalid_model`；429/quota → `rate_limit`（不再混用）
- 所有回傳路徑都包含完整 log keys

```
refactor: converge grader to fixed model, short JSON output, correct 404/429 error codes
```

---

## v3.5 — 2026-04-13

**檔案：`grader.py`**

- `_build_detail()` 新增選用參數：`model_name`、`graded_at`、`retry_count`、`request_status`、`input_tokens_est`
- 所有提前回傳路徑（empty、chinese_dominant、rate_limit、failed）現在都包含這些 key
- 修復：`admin_grading.py` 讀取 `log["model_name"]` 時拋出 `KeyError` 導致 Run AI now 失敗
- 成功路徑改為直接透過 `_build_detail` 參數設定，移除事後 `detail[...] = ...` 的寫法

```
fix: add model_name/request_status keys to all grade() return paths, fixes KeyError in admin_grading
```

---



**檔案：`grader.py`、`admin_grading.py`**

- `grader.py`：新增 `FIXED_MODEL = DEFAULT_MODEL` 向下相容別名
- `grader.py`：新增 `get_active_model()`，從 `storage.get_settings()` 讀取 `ai_model`，含白名單驗證
- `admin_grading.py`：兩處 `grader.FIXED_MODEL` → `grader.get_active_model()`
- `admin_grading.py`：兩處 `grader.grade(text, key_concepts)` → `grader.grade(text, key_concepts, model=active_model)`
- 修復：app 啟動時 `AttributeError: grader.FIXED_MODEL` 導致整個 app 壞掉

```
fix: replace grader.FIXED_MODEL with get_active_model(), pass model= to grade()
```

---

## v3.3 — 2026-04-13

**檔案：`grader.py`**

- SDK 從 `google-generativeai`（已停止支援）遷移到 `google-genai`
- `import google.generativeai as genai` → `from google import genai` + `from google.genai import types as genai_types`
- `_get_model()` → `_get_client()`，使用 `genai.Client(api_key=...)`
- `generate_content` 呼叫更新為 `client.models.generate_content()`
- `requirements.txt`：`google-generativeai` → `google-genai`
- 修復：Streamlit Cloud 部署時 ImportError

```
fix: migrate grader.py from google-generativeai to google-genai SDK
```

---

## v3.2 — 2026-04-13

**檔案：`grader.py`**

- 純中文筆記（`chinese_dominant`）的 justification 訊息修正
- 舊訊息：`Notes are primarily written in Chinese...` → 語意不清
- 新訊息：`Submission is readable, but it is written primarily in Chinese and does not meet the English-notes requirement. Grade: Missing. Please revise and resubmit in English-dominant form.`
- 與 empty/unreadable 路徑（`len < 10`）完全分開，不再混用

```
fix: chinese-dominant notes show readable-but-Chinese message, not empty/unreadable
```

---

## v3.1 — 2026-04-13

**檔案：`grader.py`**

- `chinese_dominant`（>70% 中文）從 `Poor / score=1` 改為 `Missing / score=0`
- 建立兩條獨立路徑：
  - `len < 10` → `Missing`，訊息：`Submission is empty, unreadable, or scan-only.`
  - `chinese_ratio > 0.70` → `Missing`，訊息：中文可讀但不符合要求

```
fix: reclassify chinese-dominant submissions as Missing (score=0) instead of Poor
```

---

## v3.0 — 2026-04-13

**檔案：`grader.py`**

- 等級系統從 6 級制改為 **7 級制**：`Perfect / Excellent / Great / Good / Average / Fair / Poor / Missing`
- `Missing` 為獨立狀態，不混入 7 個等級
- 新 grade boundaries：Perfect≥4.7、Excellent≥4.1、Great≥3.5、Good≥2.9、Average≥2.2、Fair≥1.5、Poor≥1.0
- `GRADE_TO_SCORE` 對應：Perfect/Excellent=5、Great=4、Good=3、Average/Fair/Poor=1-2、Missing=0
- B 維度 rubric 新增「不算高分」的明確清單（換標題、條列整理、摘要重寫 ≠ restructuring）
- 新增 calibration reminders 防止 AI 高估（well-organized summary → Average to Good，不應給 Great+）
- `needs_review` 觸發條件收緊：邊界分數、維度極端差異、語言問題、D=1 配高分
- `mixed_chinese_heavy` 語言標記新增（>30% 中文但 <70%）

```
feat: 7-level grade system + rubric calibration for average/good/great/excellent separation
```

---

## v2.x 以前（遷移前）

- 資料庫從 Google Sheets 遷移至 Supabase Database
- `storage.py` 完整重寫，底層改用 `db.py`（Supabase）
- Google Sheets 依賴完全移除
- 評分等級曾為 6 級（Excellent / Very Good / Good / Fair / Fail / Missing）
- AI 模型曾使用 `google-generativeai` 舊版 SDK

---

## 下次開新視窗時

請傳以下檔案給 AI：
1. `CHANGELOG.md`（本檔案）
2. 你要修改的檔案（最新版，從 GitHub 下載）
3. 錯誤訊息或截圖

然後說：「這是目前 GitHub 上的最新版，請從這裡開始。」
