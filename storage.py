"""
storage.py — Google Sheets + Google Drive 資料存取模組
所有資料永久存在雲端，Streamlit 重啟不會遺失
"""

import streamlit as st
import json
import io
from datetime import datetime
from typing import Optional, List, Dict, Any
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ── Google API 授權範圍 ───────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Sheets 工作表名稱 ─────────────────────────────────────────
SHEET_GRADES       = "grades"
SHEET_STUDENTS     = "students"
SHEET_SETTINGS     = "settings"
SHEET_WEEKS        = "weeks"
SHEET_ANNOUNCEMENTS = "announcements"

# ── Grades 欄位定義 ───────────────────────────────────────────
GRADE_FIELDS = [
    "semester", "student_id", "name", "week", "filename",
    "drive_url", "ai_score", "ai_justification",
    "needs_review", "scan_only", "is_late",
    "final_score", "released", "submitted_at",
]


# ════════════════════════════════════════════════════════════════
#  認證與連線（使用 st.cache_resource 避免重複建立）
# ════════════════════════════════════════════════════════════════

@st.cache_resource
def _get_gspread_client():
    """建立 gspread 認證客戶端"""
    creds_json = st.secrets["GOOGLE_CREDENTIALS"]
    if isinstance(creds_json, str):
        creds_info = json.loads(creds_json)
    else:
        creds_info = dict(creds_json)  # Streamlit TOML secrets 物件
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return gspread.authorize(creds)


@st.cache_resource
def _get_drive_service():
    """建立 Google Drive API 服務"""
    creds_json = st.secrets["GOOGLE_CREDENTIALS"]
    if isinstance(creds_json, str):
        creds_info = json.loads(creds_json)
    else:
        creds_info = dict(creds_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _get_spreadsheet():
    """取得主試算表"""
    gc = _get_gspread_client()
    sheet_id = st.secrets["GOOGLE_SHEET_ID"]
    return gc.open_by_key(sheet_id)


def _get_or_create_worksheet(ss, title: str, headers: List[str]) -> gspread.Worksheet:
    """取得或建立工作表，並確保表頭存在"""
    try:
        ws = ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws


# ════════════════════════════════════════════════════════════════
#  Settings
# ════════════════════════════════════════════════════════════════

def get_settings() -> Dict:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_SETTINGS, ["key", "value"])
        records = ws.get_all_records()
        return {r["key"]: r["value"] for r in records}
    except Exception:
        return {}


def save_setting(key: str, value: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_SETTINGS, ["key", "value"])
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            if r["key"] == key:
                ws.update_cell(i, 2, value)
                return
        ws.append_row([key, value])
    except Exception as e:
        st.error(f"Failed to save setting: {e}")


# ════════════════════════════════════════════════════════════════
#  Students
# ════════════════════════════════════════════════════════════════

def get_students(semester: str) -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_STUDENTS, ["semester", "student_id", "name"])
        records = ws.get_all_records()
        return [r for r in records if r.get("semester") == semester]
    except Exception:
        return []


def save_students(semester: str, students: List[Dict]):
    """覆蓋該學期的學生名單"""
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_STUDENTS, ["semester", "student_id", "name"])
        all_records = ws.get_all_records()
        # 保留其他學期
        other = [r for r in all_records if r.get("semester") != semester]
        new_rows = [[semester, s["student_id"].upper(), s["name"]] for s in students]
        # 重寫整張表
        all_rows = [["semester", "student_id", "name"]]
        for r in other:
            all_rows.append([r["semester"], r["student_id"], r["name"]])
        all_rows.extend(new_rows)
        ws.clear()
        ws.update(all_rows)
    except Exception as e:
        st.error(f"Failed to save students: {e}")


# ════════════════════════════════════════════════════════════════
#  Weeks（週次開放設定）
# ════════════════════════════════════════════════════════════════

WEEK_FIELDS = ["semester", "week", "open", "deadline", "key_concepts"]


def get_open_weeks(semester: str) -> List[Dict]:
    """取得該學期已開放的週次（未過截止日）"""
    all_weeks = get_all_weeks(semester)
    now = datetime.now().date()
    result = []
    for w in all_weeks:
        if str(w.get("open", "")).lower() not in ("true", "1", "yes"):
            continue
        deadline_str = w.get("deadline", "")
        if deadline_str:
            try:
                deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
                if deadline < now:
                    continue
            except ValueError:
                pass
        result.append(w)
    return result


def get_all_weeks(semester: str) -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_WEEKS, WEEK_FIELDS)
        records = ws.get_all_records()
        return [r for r in records if r.get("semester") == semester]
    except Exception:
        return []


def get_week_config(semester: str, week: str) -> Optional[Dict]:
    for w in get_all_weeks(semester):
        if str(w.get("week")) == str(week):
            return w
    return None


def save_week(semester: str, week: str, open_flag: bool, deadline: str, key_concepts: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_WEEKS, WEEK_FIELDS)
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            if r.get("semester") == semester and str(r.get("week")) == str(week):
                ws.update(f"A{i}:E{i}", [[semester, week, open_flag, deadline, key_concepts]])
                return
        ws.append_row([semester, week, open_flag, deadline, key_concepts])
    except Exception as e:
        st.error(f"Failed to save week: {e}")


# ════════════════════════════════════════════════════════════════
#  Grades
# ════════════════════════════════════════════════════════════════

def find_record(student_id: str, week: str, semester: str) -> Optional[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_GRADES, GRADE_FIELDS)
        records = ws.get_all_records()
        for r in records:
            if (r.get("student_id", "").upper() == student_id.upper()
                    and str(r.get("week")) == str(week)
                    and r.get("semester") == semester):
                return r
    except Exception:
        pass
    return None


def find_all_records_for_student(student_id: str, semester: str) -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_GRADES, GRADE_FIELDS)
        records = ws.get_all_records()
        return [r for r in records
                if r.get("student_id", "").upper() == student_id.upper()
                and r.get("semester") == semester]
    except Exception:
        return []


def load_all_records(semester: str) -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_GRADES, GRADE_FIELDS)
        records = ws.get_all_records()
        return [r for r in records if r.get("semester") == semester]
    except Exception:
        return []


def save_record(record: Dict, overwrite: bool = False):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_GRADES, GRADE_FIELDS)
        if overwrite:
            records = ws.get_all_records()
            for i, r in enumerate(records, start=2):
                if (r.get("student_id", "").upper() == record["student_id"].upper()
                        and str(r.get("week")) == str(record["week"])
                        and r.get("semester") == record["semester"]):
                    row = [str(record.get(f, "")) for f in GRADE_FIELDS]
                    ws.update(f"A{i}:{chr(64+len(GRADE_FIELDS))}{i}", [row])
                    return
        ws.append_row([str(record.get(f, "")) for f in GRADE_FIELDS])
    except Exception as e:
        st.error(f"Failed to save record: {e}")


def update_record(student_id: str, week: str, semester: str, updates: Dict):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_GRADES, GRADE_FIELDS)
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            if (r.get("student_id", "").upper() == student_id.upper()
                    and str(r.get("week")) == str(week)
                    and r.get("semester") == semester):
                merged = {**r, **updates}
                row = [str(merged.get(f, "")) for f in GRADE_FIELDS]
                ws.update(f"A{i}:{chr(64+len(GRADE_FIELDS))}{i}", [row])
                return
    except Exception as e:
        st.error(f"Failed to update record: {e}")


# ════════════════════════════════════════════════════════════════
#  Announcements
# ════════════════════════════════════════════════════════════════

ANN_FIELDS = ["id", "content", "posted_at", "active"]


def get_announcements() -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_ANNOUNCEMENTS, ANN_FIELDS)
        records = ws.get_all_records()
        return [r for r in records if str(r.get("active", "")).lower() in ("true", "1", "yes")]
    except Exception:
        return []


def save_announcement(content: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_ANNOUNCEMENTS, ANN_FIELDS)
        ann_id = datetime.now().strftime("%Y%m%d%H%M%S")
        ws.append_row([ann_id, content, datetime.now().strftime("%Y-%m-%d %H:%M"), "True"])
    except Exception as e:
        st.error(f"Failed to save announcement: {e}")


def deactivate_announcement(ann_id: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_worksheet(ss, SHEET_ANNOUNCEMENTS, ANN_FIELDS)
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            if str(r.get("id")) == str(ann_id):
                ws.update_cell(i, 4, "False")
                return
    except Exception as e:
        st.error(f"Failed to deactivate announcement: {e}")


# ════════════════════════════════════════════════════════════════
#  Google Drive — PDF 上傳
# ════════════════════════════════════════════════════════════════

def upload_pdf_to_drive(pdf_bytes: bytes, filename: str, semester: str, week: str) -> Optional[str]:
    """
    上傳 PDF 到 Google Drive，路徑：
    根資料夾 / semester / week_XX / filename
    回傳檔案的分享連結
    """
    try:
        service = _get_drive_service()
        root_folder_id = st.secrets["GOOGLE_DRIVE_FOLDER_ID"]

        # 取得或建立學期資料夾
        sem_folder_id = _get_or_create_folder(service, semester, root_folder_id)
        # 取得或建立週次資料夾
        week_folder_name = f"Week_{week.zfill(2)}"
        week_folder_id = _get_or_create_folder(service, week_folder_name, sem_folder_id)

        # 刪除同名舊檔（覆蓋時）
        _delete_file_if_exists(service, filename, week_folder_id)

        # 上傳新檔
        file_metadata = {
            "name": filename,
            "parents": [week_folder_id],
        }
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink"
        ).execute()

        return file.get("webViewLink", "")
    except Exception as e:
        st.warning(f"Drive upload failed: {e}")
        return None


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    query = (f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
             f"and '{parent_id}' in parents and trashed=false")
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _delete_file_if_exists(service, filename: str, parent_id: str):
    query = f"name='{filename}' and '{parent_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id)").execute()
    for f in results.get("files", []):
        service.files().delete(fileId=f["id"]).execute()
