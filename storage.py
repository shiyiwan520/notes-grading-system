"""
storage.py — 資料存取模組（最終版，Supabase Database）
所有資料讀寫走 db.py（Supabase Database）。
PDF 檔案仍存放於 Supabase Storage（行為不變）。
Google Sheets 依賴已完全移除。

對外 API 與舊版完全相容，上層頁面不需要修改。
"""

import streamlit as st
from datetime import datetime
from typing import Optional, List, Dict
import db

# ─────────────────────────────────────────────
# 常數
# ─────────────────────────────────────────────

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
SUPABASE_BUCKET     = "notes-pdf"


# ─────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────

def get_settings() -> Dict:
    """
    讀取系統設定。
    使用 session_state 快取，避免每次 rerun 打 DB。
    失敗時保留上次有效快取，不以空值覆蓋。
    """
    if "settings_cache" not in st.session_state:
        result = db.get_settings()
        # db.get_settings() 失敗時回傳空 {}，成功時回傳有內容的 dict
        # 空 dict 也存入快取（代表 DB 是空的，不是失敗）
        st.session_state.settings_cache = result
    return st.session_state.settings_cache


def save_setting(key: str, value: str) -> None:
    """儲存設定，同步更新 session_state 快取。失敗時拋出例外。"""
    db.save_setting(key, value)
    if "settings_cache" in st.session_state:
        st.session_state.settings_cache[key] = value


def _invalidate_settings_cache() -> None:
    """清除 settings 快取，讓下次 get_settings() 重新從 DB 讀取。"""
    if "settings_cache" in st.session_state:
        del st.session_state["settings_cache"]


# ─────────────────────────────────────────────
# Students
# ─────────────────────────────────────────────

@st.cache_data(ttl=30)
def get_students(semester: str) -> List[Dict]:
    """
    讀取學生名單（有 30 秒快取）。
    失敗時拋出例外，讓呼叫端用 get_students_safe() 處理。
    """
    return db.get_students(semester)


def get_students_safe(semester: str) -> Optional[List[Dict]]:
    """讀取學生名單，失敗時回傳 None（不拋例外）。"""
    try:
        return get_students(semester)
    except Exception:
        return None


def add_student_single(semester: str, student_id: str,
                        name: str, passcode: str = "") -> None:
    """單筆新增學生（安全 upsert）。"""
    db.upsert_student(semester, student_id, name, passcode)
    get_students.clear()


def save_students(semester: str, students: List[Dict]) -> None:
    """取代整學期學生名單（CSV 匯入用）。"""
    db.replace_students(semester, students)
    get_students.clear()


def update_student_passcode(semester: str, student_id: str,
                             passcode: str) -> bool:
    """更新學生驗證碼。"""
    ok = db.update_student_passcode(semester, student_id, passcode)
    if ok:
        get_students.clear()
    return ok


# ─────────────────────────────────────────────
# Weeks
# ─────────────────────────────────────────────

@st.cache_data(ttl=30)
def get_all_weeks(semester: str) -> List[Dict]:
    """讀取週次設定（有 30 秒快取）。"""
    return db.get_all_weeks(semester)


def get_open_weeks(semester: str) -> List[Dict]:
    """回傳目前開放且未過截止日的週次。"""
    now = datetime.now().date()
    result = []
    for w in get_all_weeks(semester):
        # 相容 DB 回傳的 True/False 和 Sheets 格式的 "true"/"1"
        open_val = w.get("open")
        if open_val is not True and \
           str(open_val).lower() not in ("true", "1", "yes"):
            continue
        dl = str(w.get("deadline", "")).strip()
        if dl and dl not in ("", "None"):
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
    """取得單週設定。"""
    week_norm = str(week).lstrip("0") or "0"
    for w in get_all_weeks(semester):
        if str(w.get("week")) == str(week) or \
           str(w.get("week")).lstrip("0") == week_norm:
            return w
    return None


def save_week(semester: str, week: str, open_flag: bool,
              deadline: str, key_concepts: str) -> None:
    """新增或更新週次設定。"""
    try:
        db.upsert_week(semester, week, open_flag, deadline, key_concepts)
        get_all_weeks.clear()
    except Exception as e:
        st.error(f"Failed to save week: {e}")


# ─────────────────────────────────────────────
# Grades / Submissions
# ─────────────────────────────────────────────

@st.cache_data(ttl=15)
def load_all_records(semester: str) -> List[Dict]:
    """讀取所有繳交記錄（有 15 秒快取）。"""
    return db.load_all_records(semester)


def find_record(student_id: str, week: str,
                semester: str) -> Optional[Dict]:
    """
    查詢單筆記錄（精確查詢，不做全表讀取）。
    用於繳交前的重複確認，每次都直接查 DB 確保準確。
    """
    return db.find_record(student_id, week, semester)


def find_all_records_for_student(student_id: str,
                                  semester: str) -> List[Dict]:
    """查詢某學生的所有記錄。"""
    return [r for r in load_all_records(semester)
            if r.get("student_id", "").upper() == student_id.upper()]


def save_record(record: Dict, overwrite: bool = False) -> None:
    """
    儲存繳交記錄（upsert by semester, student_id, week）。
    失敗時拋出例外，讓 app.py 決定如何處理。
    """
    db.save_record(record, overwrite)
    load_all_records.clear()


def update_record(student_id: str, week: str, semester: str,
                  updates: Dict) -> None:
    """更新繳交記錄的部分欄位。"""
    try:
        db.update_record(student_id, week, semester, updates)
        load_all_records.clear()
    except Exception as e:
        st.error(f"Failed to update record: {e}")


# ─────────────────────────────────────────────
# Announcements
# ─────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_announcements() -> List[Dict]:
    """讀取啟用中的公告（有 60 秒快取）。"""
    try:
        return db.get_announcements()
    except Exception:
        return []


def save_announcement(content: str) -> None:
    """新增公告。"""
    try:
        db.save_announcement(content)
        get_announcements.clear()
    except Exception as e:
        st.error(f"Failed to save announcement: {e}")


def deactivate_announcement(ann_id: str) -> None:
    """停用公告。"""
    try:
        db.deactivate_announcement(ann_id)
        get_announcements.clear()
    except Exception as e:
        st.error(f"Failed to deactivate: {e}")


# ─────────────────────────────────────────────
# Supabase Storage — PDF 上傳與管理
# 這部分維持不變，storage_path 是長期依賴
# ─────────────────────────────────────────────

@st.cache_resource
def _get_supabase():
    from supabase import create_client
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


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
    上傳 PDF 到 Supabase Storage（固定路徑 upsert）。
    路徑格式：{semester}/Week_{week}/{student_id}.pdf
    storage_path 是永久有效的主要依賴。
    file_url 是產生的 signed URL，有效期 1 年（可重算）。
    """
    storage_path = f"{semester}/Week_{str(week).zfill(2)}/{student_id}.pdf"
    try:
        sb = _get_supabase()
        sb.storage.from_(SUPABASE_BUCKET).upload(
            path=storage_path,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        try:
            signed   = sb.storage.from_(SUPABASE_BUCKET).create_signed_url(
                storage_path, expires_in=365 * 24 * 3600
            )
            file_url = (signed.get("signedURL")
                        or signed.get("signed_url")
                        or signed.get("signedUrl")
                        or "")
        except Exception as sign_err:
            file_url = ""
            st.warning(f"PDF uploaded but signed URL failed: {sign_err}")

        return {
            "success":        True,
            "storage_path":   storage_path,
            "file_url":       file_url,
            "file_size_bytes": len(pdf_bytes),
            "error":          "",
        }
    except Exception as e:
        return {
            "success":        False,
            "storage_path":   "",
            "file_url":       "",
            "file_size_bytes": len(pdf_bytes),
            "error":          str(e),
        }


def delete_old_pdf(old_storage_path: str) -> bool:
    """刪除 Supabase Storage 上的 PDF。"""
    if not old_storage_path:
        return True
    try:
        _get_supabase().storage.from_(SUPABASE_BUCKET).remove([old_storage_path])
        return True
    except Exception as e:
        print(f"[delete_old_pdf] Failed: {e}")
        return False


def get_pdf_signed_url(storage_path: str,
                        expires_in: int = 3600) -> Optional[str]:
    """
    即時產生 signed URL（短期有效，用於老師預覽/下載）。
    系統以 storage_path 為主依賴，file_url 只作快取用。
    """
    if not storage_path:
        return None
    try:
        result = _get_supabase().storage.from_(SUPABASE_BUCKET) \
            .create_signed_url(storage_path, expires_in=expires_in)
        return result.get("signedURL") or result.get("signed_url")
    except Exception:
        return None


def get_storage_stats(semester: str) -> Dict:
    """計算儲存空間使用摘要。"""
    records     = load_all_records(semester)
    total_bytes = sum(
        int(r.get("file_size_bytes", 0))
        for r in records
        if str(r.get("file_size_bytes", "0")).isdigit()
    )
    return {
        "total_files": len(records),
        "total_bytes": total_bytes,
        "total_mb":    round(total_bytes / (1024 * 1024), 2),
    }


# ─────────────────────────────────────────────
# 向下相容
# ─────────────────────────────────────────────

def upload_pdf_to_drive(pdf_bytes, filename, semester, week):
    return None
