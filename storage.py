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
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

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
    "semester", "student_id", "name", "week", "filename",
    "drive_url", "ai_score", "ai_justification",
    "needs_review", "scan_only", "is_late",
    "final_score", "released", "submitted_at",
]

WEEK_FIELDS = ["semester", "week", "open", "deadline", "key_concepts"]
ANN_FIELDS  = ["id", "content", "posted_at", "active"]


@st.cache_resource
def _get_gspread_client():
    creds = Credentials.from_service_account_info(_load_creds(), scopes=SCOPES)
    return gspread.authorize(creds)


@st.cache_resource
def _get_drive_service():
    creds = Credentials.from_service_account_info(_load_creds(), scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _load_creds():
    creds_json = st.secrets["GOOGLE_CREDENTIALS"]
    return json.loads(creds_json) if isinstance(creds_json, str) else dict(creds_json)


def _get_spreadsheet():
    return _get_gspread_client().open_by_key(st.secrets["GOOGLE_SHEET_ID"])


def _get_or_create_ws(ss, title: str, headers: List[str]) -> gspread.Worksheet:
    try:
        return ss.worksheet(title)
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


@st.cache_data(ttl=30)
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
    try:
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
    except Exception as e:
        st.error(f"Failed to save students: {e}")


def update_student_passcode(semester: str, student_id: str, passcode: str):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_STUDENTS, STUDENT_FIELDS)
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):
            if (r.get("semester") == semester
                    and r.get("student_id","").upper() == student_id.upper()):
                ws.update_cell(i, 4, passcode)
                _invalidate()
                return True
        return False
    except Exception as e:
        st.error(f"Failed to update passcode: {e}")
        return False


# ── Weeks ─────────────────────────────────────────────────────

@st.cache_data(ttl=30)
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

@st.cache_data(ttl=15)
def load_all_records(semester: str) -> List[Dict]:
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_GRADES, GRADE_FIELDS)
        return [r for r in ws.get_all_records() if r.get("semester") == semester]
    except Exception:
        return []


def find_record(student_id: str, week: str, semester: str) -> Optional[Dict]:
    for r in load_all_records(semester):
        if (r.get("student_id", "").upper() == student_id.upper()
                and str(r.get("week")) == str(week)):
            return r
    return None


def find_all_records_for_student(student_id: str, semester: str) -> List[Dict]:
    return [r for r in load_all_records(semester)
            if r.get("student_id", "").upper() == student_id.upper()]


def save_record(record: Dict, overwrite: bool = False):
    try:
        ss = _get_spreadsheet()
        ws = _get_or_create_ws(ss, SHEET_GRADES, GRADE_FIELDS)
        if overwrite:
            for i, r in enumerate(ws.get_all_records(), start=2):
                if (r.get("student_id", "").upper() == record["student_id"].upper()
                        and str(r.get("week")) == str(record["week"])
                        and r.get("semester") == record["semester"]):
                    ws.update(f"A{i}:{chr(64+len(GRADE_FIELDS))}{i}",
                              [[str(record.get(f, "")) for f in GRADE_FIELDS]])
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
                          [[str(merged.get(f, "")) for f in GRADE_FIELDS]])
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

def upload_pdf_to_drive(pdf_bytes: bytes, filename: str, semester: str, week: str) -> Optional[str]:
    try:
        service = _get_drive_service()
        root = st.secrets["GOOGLE_DRIVE_FOLDER_ID"]
        sem_folder = _get_or_create_folder(service, semester, root)
        week_folder = _get_or_create_folder(service, f"Week_{str(week).zfill(2)}", sem_folder)
        _delete_file_if_exists(service, filename, week_folder)
        file = service.files().create(
            body={"name": filename, "parents": [week_folder]},
            media_body=MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf"),
            fields="id, webViewLink",
            supportsAllDrives=True
        ).execute()
        return file.get("webViewLink", "")
    except Exception as e:
        st.warning(f"Drive upload failed: {e}")
        return None


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    results = service.files().list(
        q=(f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
           f"and '{parent_id}' in parents and trashed=false"),
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    return service.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder",
              "parents": [parent_id]},
        fields="id",
        supportsAllDrives=True
    ).execute()["id"]


def _delete_file_if_exists(service, filename: str, parent_id: str):
    results = service.files().list(
        q=f"name='{filename}' and '{parent_id}' in parents and trashed=false",
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    for f in results.get("files", []):
        service.files().delete(
            fileId=f["id"],
            supportsAllDrives=True
        ).execute()
