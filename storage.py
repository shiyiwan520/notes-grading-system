"""
storage.py — Google Sheets + Google Drive 資料存取模組
修正版：寫入後立即清除快取，避免資料不同步問題
"""

import streamlit as st
import json
import io
from datetime import datetime
from typing import Optional, List, Dict
import gspread
from google.oauth2.service_account import Credentials
# Google Drive removed - PDFs stored in Sheets as base64

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_GRADES        = "grades"
SHEET_STUDENTS      = "students"
SHEET_SETTINGS      = "settings"
SHEET_WEEKS         = "weeks"
SHEET_ANNOUNCEMENTS = "announcements"

GRADE_FIELDS = [
    "semester", "student_id", "name", "week",
    "original_filename", "file_size_bytes", "storage_bucket",
    "storage_path", "file_url",
    "replaced_previous",
    "ai_score", "ai_justification",
    "teacher_justification",
    "needs_review", "scan_only", "is_late",
    "final_score", "released", "submitted_at",
    # AI request logging
    "ai_model", "ai_graded_at", "ai_retry_count",
    "ai_request_status", "ai_input_tokens_est",
]

# backward-compat alias
LEGACY_FIELD_MAP = {"drive_url": "file_url", "filename": "original_filename"}

WEEK_FIELDS = ["semester", "week", "open", "deadline", "key_concepts"]
ANN_FIELDS  = ["id", "content", "posted_at", "active"]


@st.cache_resource
def _get_gspread_client():
    creds = Credentials.from_service_account_info(_load_creds(), scopes=SCOPES)
    return gspread.authorize(creds)





def _load_creds():
    creds_json = st.secrets["GOOGLE_CREDENTIALS"]
    return json.loads(creds_json) if isinstance(creds_json, str) else dict(creds_json)


def _get_spreadsheet():
    return _get_gspread_client().open_by_key(st.secrets["GOOGLE_SHEET_ID"])


def _get_or_create_ws(ss, title: str, headers: List[str]) -> gspread.Worksheet:
    try:
        ws = ss.worksheet(title)
        # 若已存在，檢查並補齊缺少的欄位（向後相容）
        existing_headers = ws.row_values(1) if ws.row_count > 0 else []
        if existing_headers:
            for h in headers:
                if h not in existing_headers:
                    col = len(existing_headers) + 1
                    ws.update_cell(1, col, h)
                    existing_headers.append(h)
        else:
            ws.append_row(headers)
        return ws
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=1000, cols=max(len(headers), 10))
        ws.append_row(headers)
        return ws


def _invalidate():
    st.cache_data.clear()


# ── Settings ──────────────────────────────────────────────────

def get_settings() -> Dict:
    if "settings_cache" not in st.session_state:
        st.session_state.settings_cache = _fetch_settings()
    return st.session_state.settings_cache


def _fetch_settings() -> Dict:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_SETTINGS, ["key", "value"])
        return {r["key"]: r["value"] for r in ws.get_all_records() if r.get("key")}
    except Exception:
        return {}


def save_setting(key: str, value: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_SETTINGS, ["key", "value"])
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            if r.get("key") == key:
                ws.update_cell(i, 2, value)
                if "settings_cache" in st.session_state:
                    st.session_state.settings_cache[key] = value
                return
        ws.append_row([key, value])
        if "settings_cache" in st.session_state:
            st.session_state.settings_cache[key] = value
    except Exception as e:
        st.error(f"Failed to save setting: {e}")


# ── Students ──────────────────────────────────────────────────

STUDENT_FIELDS = ["semester", "student_id", "name", "passcode"]


@st.cache_data(ttl=5)
def get_students(semester: str) -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_STUDENTS, STUDENT_FIELDS)
        return [r for r in ws.get_all_records()
                if r.get("semester") == semester
                and str(r.get("student_id", "")).strip() not in ("", "student_id")]
    except Exception:
        return []


def save_students(semester: str, students: List[Dict]):
    ss = _get_spreadsheet()
    ws = _get_or_create_ws(ss, SHEET_STUDENTS, STUDENT_FIELDS)
    other = [r for r in ws.get_all_records() if r.get("semester") != semester]
    all_rows = [STUDENT_FIELDS]
    for r in other:
        all_rows.append([r.get("semester",""), r.get("student_id",""),
                         r.get("name",""), r.get("passcode","")])
    for s in students:
        all_rows.append([semester, s["student_id"].upper(),
                         s["name"], s.get("passcode","")])
    ws.clear()
    ws.update(all_rows)
    _invalidate()


def update_student_passcode(semester: str, student_id: str, passcode: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_STUDENTS, STUDENT_FIELDS)
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            if (r.get("semester") == semester
                    and r.get("student_id","").upper() == student_id.upper()):
                # 強制以文字格式存入，避免 Sheets 把 0924 變成 924
                cell = gspread.utils.rowcol_to_a1(i, 4)
                ws.update(
                    cell,
                    [[passcode]],
                    value_input_option="RAW"
                )
                # 額外設定儲存格格式為純文字
                try:
                    ss2 = _get_spreadsheet()
                    ws2 = ss2.worksheet(SHEET_STUDENTS)
                    ws2.format(cell, {"numberFormat": {"type": "TEXT"}})
                except Exception:
                    pass
                _invalidate()
                return True
        return False
    except Exception as e:
        st.error(f"Failed to update passcode: {e}")
        return False


# ── Weeks ─────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def get_all_weeks(semester: str) -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_WEEKS, WEEK_FIELDS)
        return [r for r in ws.get_all_records() if r.get("semester") == semester]
    except Exception:
        return []


def get_open_weeks(semester: str) -> List[Dict]:
    now = datetime.now().date()
    result = []
    for w in get_all_weeks(semester):
        if str(w.get("open", "")).lower() not in ("true", "1", "yes"):
            continue
        dl = str(w.get("deadline", "")).strip()
        if dl:
            try:
                if datetime.strptime(dl, "%Y-%m-%d").date() < now:
                    continue
            except ValueError:
                pass
        w_copy = dict(w)
        w_copy["week"] = str(w_copy.get("week", "")).zfill(2)
        result.append(w_copy)
    return result


def get_week_config(semester: str, week: str) -> Optional[Dict]:
    for w in get_all_weeks(semester):
        if str(w.get("week")) == str(week):
            return w
    return None


def save_week(semester: str, week: str, open_flag: bool, deadline: str, key_concepts: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_WEEKS, WEEK_FIELDS)
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            if r.get("semester") == semester and str(r.get("week")) == str(week):
                ws.update(f"A{i}:E{i}", [[semester, week, open_flag, deadline, key_concepts]])
                _invalidate()
                return
        ws.append_row([semester, week, open_flag, deadline, key_concepts])
        _invalidate()
    except Exception as e:
        st.error(f"Failed to save week: {e}")


# ── Grades ────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def load_all_records(semester: str) -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_GRADES, GRADE_FIELDS)
        return [r for r in ws.get_all_records() if r.get("semester") == semester]
    except Exception:
        return []


def find_record(student_id: str, week: str, semester: str) -> Optional[Dict]:
    """即時查詢，不使用快取，確保覆蓋確認的準確性"""
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_GRADES, GRADE_FIELDS)
        # 正規化週次：去掉前導零做比對，例如 "05" == "5" == 5
        week_norm = str(int(str(week).lstrip("0") or "0"))
        for r in ws.get_all_records():
            r_week = str(r.get("week","")).lstrip("0") or "0"
            if (r.get("semester") == semester
                    and r.get("student_id", "").upper() == student_id.upper()
                    and r_week == week_norm):
                return r
    except Exception:
        pass
    return None


def find_all_records_for_student(student_id: str, semester: str) -> List[Dict]:
    return [r for r in load_all_records(semester)
            if r.get("student_id", "").upper() == student_id.upper()]


def save_record(record: Dict, overwrite: bool = False):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_GRADES, GRADE_FIELDS)
        if overwrite:
            week_norm = str(int(str(record["week"]).lstrip("0") or "0"))
            for i, r in enumerate(ws.get_all_records(), start=2):
                r_week = str(r.get("week","")).lstrip("0") or "0"
                if (r.get("student_id", "").upper() == record["student_id"].upper()
                        and r_week == week_norm
                        and r.get("semester") == record["semester"]):
                    ws.update(f"A{i}:{chr(64+len(GRADE_FIELDS))}{i}",
                              [[str(record.get(f, "")) for f in GRADE_FIELDS]],
                              value_input_option="RAW")
                    _invalidate()
                    return
        ws.append_row([str(record.get(f, "")) for f in GRADE_FIELDS])
        _invalidate()
    except Exception as e:
        st.error(f"Failed to save record: {e}")


def update_record(student_id: str, week: str, semester: str, updates: Dict):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_GRADES, GRADE_FIELDS)
        for i, r in enumerate(ws.get_all_records(), start=2):
            if (r.get("student_id", "").upper() == student_id.upper()
                    and str(r.get("week")) == str(week)
                    and r.get("semester") == semester):
                merged = {**r, **updates}
                ws.update(f"A{i}:{chr(64+len(GRADE_FIELDS))}{i}",
                          [[str(merged.get(f, "")) for f in GRADE_FIELDS]],
                          value_input_option="RAW")
                _invalidate()
                return
    except Exception as e:
        st.error(f"Failed to update record: {e}")


# ── Announcements ─────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_announcements() -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_ANNOUNCEMENTS, ANN_FIELDS)
        return [r for r in ws.get_all_records()
                if str(r.get("active", "")).lower() in ("true", "1", "yes")]
    except Exception:
        return []


def save_announcement(content: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_ANNOUNCEMENTS, ANN_FIELDS)
        ws.append_row([datetime.now().strftime("%Y%m%d%H%M%S"), content,
                       datetime.now().strftime("%Y-%m-%d %H:%M"), "True"])
        _invalidate()
    except Exception as e:
        st.error(f"Failed to save announcement: {e}")


def deactivate_announcement(ann_id: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_ANNOUNCEMENTS, ANN_FIELDS)
        for i, r in enumerate(ws.get_all_records(), start=2):
            if str(r.get("id")) == str(ann_id):
                ws.update_cell(i, 4, "False")
                _invalidate()
                return
    except Exception as e:
        st.error(f"Failed to deactivate: {e}")


# ── Google Drive ──────────────────────────────────────────────

# ════════════════════════════════════════════════════════════════
#  Supabase Storage — PDF 上傳與管理
# ════════════════════════════════════════════════════════════════

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
SUPABASE_BUCKET = "notes-pdf"


@st.cache_resource
def _get_supabase():
    """建立 Supabase client（server-side only，key 不暴露前端）"""
    from supabase import create_client
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def upload_pdf(
    pdf_bytes: bytes,
    original_filename: str,
    student_id: str,
    student_name: str,
    semester: str,
    week: str,
    old_storage_path: Optional[str] = None,
) -> Dict:
    """
    安全上傳 PDF 到 Supabase Storage。
    使用固定路徑（學號_週次），upsert=true 直接覆蓋舊檔，
    永遠不會有殘留舊檔，無需手動刪除。
    路徑格式：{semester}/Week_{week}/{student_id}.pdf
    """
    # 固定路徑：同一學生同一週永遠是同一個檔案位置
    storage_path = f"{semester}/Week_{str(week).zfill(2)}/{student_id}.pdf"

    try:
        sb = _get_supabase()
        # upsert=true：路徑已存在就直接覆蓋，不存在就新建
        upload_resp = sb.storage.from_(SUPABASE_BUCKET).upload(
            path=storage_path,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        # 產生 signed URL（有效期 1 年）
        try:
            signed = sb.storage.from_(SUPABASE_BUCKET).create_signed_url(
                storage_path, expires_in=365 * 24 * 3600
            )
            file_url = (
                signed.get("signedURL")
                or signed.get("signed_url")
                or signed.get("signedUrl")
                or ""
            )
        except Exception as sign_err:
            file_url = ""
            st.warning(f"PDF uploaded but signed URL failed: {sign_err}")

        return {
            "success": True,
            "storage_path": storage_path,
            "file_url": file_url,
            "file_size_bytes": len(pdf_bytes),
            "error": "",
        }
    except Exception as e:
        error_detail = str(e)
        st.warning(f"[Debug] Supabase upload error: {error_detail[:200]}")
        return {
            "success": False,
            "storage_path": "",
            "file_url": "",
            "file_size_bytes": len(pdf_bytes),
            "error": error_detail,
        }


def delete_old_pdf(old_storage_path: str) -> bool:
    """刪除 Supabase 上的舊版 PDF（只在新檔和 Sheets 都確認後呼叫）"""
    if not old_storage_path:
        return True
    try:
        sb = _get_supabase()
        result = sb.storage.from_(SUPABASE_BUCKET).remove([old_storage_path])
        return True
    except Exception as e:
        print(f"[delete_old_pdf] Failed to delete {old_storage_path}: {e}")
        return False


def get_pdf_signed_url(storage_path: str, expires_in: int = 3600) -> Optional[str]:
    """產生有效期限的 signed URL 供老師下載/預覽（預設 1 小時）"""
    if not storage_path:
        return None
    try:
        sb = _get_supabase()
        result = sb.storage.from_(SUPABASE_BUCKET).create_signed_url(
            storage_path, expires_in=expires_in
        )
        return result.get("signedURL") or result.get("signed_url")
    except Exception:
        return None


def get_storage_stats(semester: str) -> Dict:
    """計算目前學期的儲存空間使用摘要"""
    records = load_all_records(semester)
    total_files = len(records)
    total_bytes = sum(
        int(r.get("file_size_bytes", 0))
        for r in records
        if str(r.get("file_size_bytes", "0")).isdigit()
    )
    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
    }


# backward compat - 舊程式碼可能還呼叫這個
def upload_pdf_to_drive(pdf_bytes, filename, semester, week):
    return None
