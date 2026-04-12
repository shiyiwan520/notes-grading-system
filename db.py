"""
db.py — Supabase Database 存取層（最終版）
取代 Google Sheets 作為主資料來源。

安全性說明：
  SUPABASE_KEY 使用 service_role key，只從 st.secrets 讀取，
  不寫死在程式碼中，不進入 git repo。
  service_role key 繞過 RLS，僅用於 server-side（Streamlit Cloud）。
"""

import streamlit as st
from typing import Optional, List, Dict


# ─────────────────────────────────────────────
# Supabase client
# ─────────────────────────────────────────────

@st.cache_resource
def _get_db():
    """
    取得 Supabase client。
    使用 service_role key（從 Streamlit Secrets 讀取，不暴露在前端或 repo）。
    """
    from supabase import create_client
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],   # service_role key，僅 server side
    )


# ─────────────────────────────────────────────
# 型別轉換工具
# ─────────────────────────────────────────────

def _to_int_or_none(v) -> Optional[int]:
    """把字串/None 轉成 int，無效值回傳 None。"""
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes")


def _row_to_record(r: Dict) -> Dict:
    """
    把 Supabase row 轉成 app 內部用的 dict 格式。
    數值欄位轉回字串（維持與舊版 Sheets 的相容性）。
    file_url 保留，但上層不應作為長期依賴（隨時可重算）。
    """
    def _str(v):
        return "" if v is None else str(v)

    return {
        "semester":              _str(r.get("semester")),
        "student_id":            _str(r.get("student_id")),
        "name":                  _str(r.get("name")),
        "week":                  _str(r.get("week")),
        "original_filename":     _str(r.get("original_filename")),
        "file_size_bytes":       _str(r.get("file_size_bytes", 0)),
        "storage_bucket":        "notes-pdf",
        "storage_path":          _str(r.get("storage_path")),    # 主要依賴
        "file_url":              _str(r.get("file_url")),         # 暫時快取
        "replaced_previous":     str(r.get("replaced_previous", False)),
        # AI 評分（DB 是 SMALLINT，回傳字串供上層使用）
        "ai_score":              _str(r.get("ai_score")),
        "ai_justification":      _str(r.get("ai_justification")),
        "ai_model":              _str(r.get("ai_model")),
        "ai_graded_at":          _str(r.get("ai_graded_at")),
        "ai_retry_count":        _str(r.get("ai_retry_count", 0)),
        "ai_request_status":     _str(r.get("ai_request_status")),
        "ai_input_tokens_est":   _str(r.get("ai_input_tokens_est", 0)),
        "language_compliance":   _str(r.get("language_compliance")),
        # 老師操作
        "teacher_justification": _str(r.get("teacher_justification")),
        "final_score":           _str(r.get("final_score")),
        "released":              str(r.get("released", False)),
        # 狀態旗標
        "needs_review":          str(r.get("needs_review", False)),
        "scan_only":             str(r.get("scan_only", False)),
        "is_late":               str(r.get("is_late", False)),
        # 時間戳
        "submitted_at":          _str(r.get("submitted_at")),
        "updated_at":            _str(r.get("updated_at")),
    }


def _record_to_row(record: Dict) -> Dict:
    """
    把 app 內部 record dict 轉成 Supabase row 格式。
    字串數值轉回正確型別（SMALLINT / INTEGER / BOOLEAN）。
    """
    return {
        "semester":              str(record.get("semester", "")),
        "student_id":            str(record.get("student_id", "")),
        "name":                  str(record.get("name", "")),
        "week":                  str(record.get("week", "")),
        "original_filename":     str(record.get("original_filename", "")),
        "file_size_bytes":       int(record.get("file_size_bytes", 0) or 0),
        "storage_path":          str(record.get("storage_path", "")),
        "file_url":              str(record.get("file_url", "")),
        "replaced_previous":     _to_bool(record.get("replaced_previous", False)),
        "ai_score":              _to_int_or_none(record.get("ai_score")),
        "ai_justification":      str(record.get("ai_justification", "")),
        "ai_model":              str(record.get("ai_model", "")),
        "ai_graded_at":          str(record.get("ai_graded_at", "")),
        "ai_retry_count":        int(record.get("ai_retry_count", 0) or 0),
        "ai_request_status":     str(record.get("ai_request_status", "")),
        "ai_input_tokens_est":   int(record.get("ai_input_tokens_est", 0) or 0),
        "language_compliance":   str(record.get("language_compliance", "")),
        "teacher_justification": str(record.get("teacher_justification", "")),
        "final_score":           _to_int_or_none(record.get("final_score")),
        "released":              _to_bool(record.get("released", False)),
        "needs_review":          _to_bool(record.get("needs_review", False)),
        "scan_only":             _to_bool(record.get("scan_only", False)),
        "is_late":               _to_bool(record.get("is_late", False)),
        "submitted_at":          str(record.get("submitted_at", "")),
    }


def _updates_to_row(updates: Dict) -> Dict:
    """
    把 update_record 傳入的部分欄位 dict 轉換型別。
    只轉換有出現的欄位，不補齊其他欄位。
    """
    int_fields      = {"file_size_bytes", "ai_retry_count", "ai_input_tokens_est"}
    smallint_fields = {"ai_score", "final_score"}
    bool_fields     = {"needs_review", "scan_only", "is_late",
                       "released", "replaced_previous"}
    clean = {}
    for k, v in updates.items():
        if k in bool_fields:
            clean[k] = _to_bool(v)
        elif k in smallint_fields:
            clean[k] = _to_int_or_none(v)
        elif k in int_fields:
            clean[k] = int(v or 0)
        else:
            clean[k] = str(v) if v is not None else ""
    return clean


# ─────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────

def get_settings() -> Dict:
    """讀取所有設定。失敗回傳空 dict。"""
    try:
        res = _get_db().table("settings").select("key, value").execute()
        return {r["key"]: r["value"] for r in (res.data or [])}
    except Exception:
        return {}


def save_setting(key: str, value: str) -> None:
    """新增或更新單筆設定（upsert）。"""
    _get_db().table("settings").upsert(
        {"key": key, "value": value},
        on_conflict="key"
    ).execute()


# ─────────────────────────────────────────────
# Students
# ─────────────────────────────────────────────

def get_students(semester: str) -> List[Dict]:
    """讀取指定學期的學生名單。"""
    res = _get_db().table("students") \
        .select("semester, student_id, name, passcode") \
        .eq("semester", semester) \
        .execute()
    return res.data or []


def upsert_student(semester: str, student_id: str,
                   name: str, passcode: str = "") -> None:
    """新增或更新單筆學生。"""
    _get_db().table("students").upsert(
        {"semester": semester, "student_id": student_id.upper(),
         "name": name, "passcode": passcode},
        on_conflict="semester,student_id"
    ).execute()


def replace_students(semester: str, students: List[Dict]) -> None:
    """取代整學期學生名單（先刪後插）。"""
    db = _get_db()
    db.table("students").delete().eq("semester", semester).execute()
    if students:
        rows = [
            {"semester": semester,
             "student_id": s["student_id"].upper(),
             "name": s["name"],
             "passcode": s.get("passcode", "")}
            for s in students
        ]
        db.table("students").insert(rows).execute()


def update_student_passcode(semester: str, student_id: str,
                             passcode: str) -> bool:
    """更新學生驗證碼。"""
    try:
        _get_db().table("students") \
            .update({"passcode": passcode}) \
            .eq("semester", semester) \
            .eq("student_id", student_id.upper()) \
            .execute()
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# Weeks
# ─────────────────────────────────────────────

def get_all_weeks(semester: str) -> List[Dict]:
    """讀取指定學期的所有週次設定。回傳格式對齊舊版 Sheets。"""
    res = _get_db().table("weeks") \
        .select("semester, week, open, deadline, key_concepts") \
        .eq("semester", semester) \
        .execute()
    rows = []
    for r in (res.data or []):
        rows.append({
            "semester":     r["semester"],
            "week":         str(r["week"]).zfill(2),
            "open":         r["open"],
            "deadline":     str(r["deadline"]) if r["deadline"] else "",
            "key_concepts": r.get("key_concepts", ""),
        })
    return rows


def upsert_week(semester: str, week: str, open_flag: bool,
                deadline: str, key_concepts: str) -> None:
    """新增或更新週次設定。"""
    _get_db().table("weeks").upsert(
        {"semester":     semester,
         "week":         week,
         "open":         open_flag,
         "deadline":     deadline if deadline else None,
         "key_concepts": key_concepts},
        on_conflict="semester,week"
    ).execute()


# ─────────────────────────────────────────────
# Submissions
# ─────────────────────────────────────────────

def load_all_records(semester: str) -> List[Dict]:
    """讀取指定學期所有繳交記錄。"""
    try:
        res = _get_db().table("submissions") \
            .select("*") \
            .eq("semester", semester) \
            .execute()
        return [_row_to_record(r) for r in (res.data or [])]
    except Exception:
        return []


def find_record(student_id: str, week: str,
                semester: str) -> Optional[Dict]:
    """精確查詢單筆記錄（不做全表讀取）。"""
    try:
        res = _get_db().table("submissions") \
            .select("*") \
            .eq("semester", semester) \
            .eq("student_id", student_id.upper()) \
            .eq("week", str(week)) \
            .limit(1) \
            .execute()
        if res.data:
            return _row_to_record(res.data[0])
    except Exception:
        pass
    return None


def save_record(record: Dict, overwrite: bool = False) -> None:
    """
    儲存繳交記錄（upsert by semester, student_id, week）。
    overwrite 參數保留供相容性，實際上 upsert 本身就會覆蓋。
    """
    row = _record_to_row(record)
    _get_db().table("submissions").upsert(
        row,
        on_conflict="semester,student_id,week"
    ).execute()


def update_record(student_id: str, week: str, semester: str,
                  updates: Dict) -> None:
    """更新繳交記錄的部分欄位。updated_at 由 DB trigger 自動更新。"""
    clean = _updates_to_row(updates)
    if not clean:
        return
    _get_db().table("submissions") \
        .update(clean) \
        .eq("semester", semester) \
        .eq("student_id", student_id.upper()) \
        .eq("week", str(week)) \
        .execute()


# ─────────────────────────────────────────────
# Announcements
# ─────────────────────────────────────────────

def get_announcements() -> List[Dict]:
    """讀取啟用中的公告。"""
    try:
        res = _get_db().table("announcements") \
            .select("*") \
            .eq("active", True) \
            .execute()
        return res.data or []
    except Exception:
        return []


def save_announcement(content: str) -> None:
    """新增公告。"""
    from datetime import datetime
    now = datetime.now()
    _get_db().table("announcements").insert({
        "id":        now.strftime("%Y%m%d%H%M%S"),
        "content":   content,
        "posted_at": now.strftime("%Y-%m-%d %H:%M"),
        "active":    True,
    }).execute()


def deactivate_announcement(ann_id: str) -> None:
    """停用公告。"""
    _get_db().table("announcements") \
        .update({"active": False}) \
        .eq("id", ann_id) \
        .execute()
