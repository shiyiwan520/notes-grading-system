"""
migrate_to_supabase.py
把 Google Sheets 現有資料搬到 Supabase Database。

使用方式：
  在本地端執行（需要安裝套件並設定環境變數）：

  1. 安裝套件：
     pip install gspread google-auth supabase python-dotenv

  2. 建立 .env 檔案（或直接設定環境變數）：
     SUPABASE_URL=https://xxxx.supabase.co
     SUPABASE_KEY=sb_secret_xxxx
     GOOGLE_SHEET_ID=你的_sheet_id

  3. 把 Google credentials JSON 存成 google_credentials.json

  4. 執行：
     python migrate_to_supabase.py

注意：這個 script 只需要執行一次，執行後 Sheets 資料就全部在 Supabase 了。
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY")
SHEET_ID      = os.getenv("GOOGLE_SHEET_ID")
CREDS_FILE    = "google_credentials.json"


def get_supabase():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_sheets_client():
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=scopes)
    return gspread.authorize(creds)


def migrate_settings(gc, sb):
    print("Migrating settings...")
    try:
        ws = gc.open_by_key(SHEET_ID).worksheet("settings")
        rows = ws.get_all_records()
        for r in rows:
            if r.get("key"):
                sb.table("settings").upsert(
                    {"key": r["key"], "value": str(r.get("value", ""))},
                    on_conflict="key"
                ).execute()
        print(f"  ✅ {len(rows)} settings migrated")
    except Exception as e:
        print(f"  ⚠️  settings: {e}")


def migrate_students(gc, sb):
    print("Migrating students...")
    try:
        ws = gc.open_by_key(SHEET_ID).worksheet("students")
        rows = ws.get_all_records()
        migrated = 0
        for r in rows:
            sid = str(r.get("student_id", "")).strip()
            if not sid or sid.lower() == "student_id":
                continue
            sb.table("students").upsert({
                "semester":   str(r.get("semester", "")),
                "student_id": sid.upper(),
                "name":       str(r.get("name", "")),
                "passcode":   str(r.get("passcode", "")),
            }, on_conflict="semester,student_id").execute()
            migrated += 1
        print(f"  ✅ {migrated} students migrated")
    except Exception as e:
        print(f"  ⚠️  students: {e}")


def migrate_weeks(gc, sb):
    print("Migrating weeks...")
    try:
        ws = gc.open_by_key(SHEET_ID).worksheet("weeks")
        rows = ws.get_all_records()
        migrated = 0
        for r in rows:
            week = str(r.get("week", "")).strip()
            if not week or week.lower() == "week":
                continue
            open_flag = str(r.get("open", "")).lower() in ("true", "1", "yes")
            deadline = str(r.get("deadline", "")).strip()
            sb.table("weeks").upsert({
                "semester":     str(r.get("semester", "")),
                "week":         week,
                "open":         open_flag,
                "deadline":     deadline if deadline else None,
                "key_concepts": str(r.get("key_concepts", "")),
            }, on_conflict="semester,week").execute()
            migrated += 1
        print(f"  ✅ {migrated} weeks migrated")
    except Exception as e:
        print(f"  ⚠️  weeks: {e}")


def migrate_grades(gc, sb):
    print("Migrating submissions/grades...")
    try:
        ws = gc.open_by_key(SHEET_ID).worksheet("grades")
        rows = ws.get_all_records()
        migrated = 0

        def _bool(v):
            return str(v).lower() in ("true", "1", "yes")

        for r in rows:
            sid = str(r.get("student_id", "")).strip()
            week = str(r.get("week", "")).strip()
            sem  = str(r.get("semester", "")).strip()
            if not sid or not week or not sem:
                continue
            sb.table("submissions").upsert({
                "semester":            sem,
                "student_id":          sid.upper(),
                "name":                str(r.get("name", "")),
                "week":                week,
                "original_filename":   str(r.get("original_filename", r.get("filename", ""))),
                "file_size_bytes":     int(r.get("file_size_bytes", 0) or 0),
                "storage_path":        str(r.get("storage_path", "")),
                "file_url":            str(r.get("file_url", r.get("drive_url", ""))),
                "replaced_previous":   _bool(r.get("replaced_previous", False)),
                "ai_score":            str(r.get("ai_score", "")),
                "ai_justification":    str(r.get("ai_justification", "")),
                "teacher_justification": str(r.get("teacher_justification", "")),
                "needs_review":        _bool(r.get("needs_review", False)),
                "scan_only":           _bool(r.get("scan_only", False)),
                "is_late":             _bool(r.get("is_late", False)),
                "final_score":         str(r.get("final_score", "")),
                "released":            _bool(r.get("released", False)),
                "ai_model":            str(r.get("ai_model", "")),
                "ai_graded_at":        str(r.get("ai_graded_at", "")),
                "ai_retry_count":      str(r.get("ai_retry_count", "")),
                "ai_request_status":   str(r.get("ai_request_status", "")),
                "ai_input_tokens_est": str(r.get("ai_input_tokens_est", "")),
                "language_compliance": str(r.get("language_compliance", "")),
                "submitted_at":        str(r.get("submitted_at", "")),
            }, on_conflict="semester,student_id,week").execute()
            migrated += 1
        print(f"  ✅ {migrated} submissions migrated")
    except Exception as e:
        print(f"  ⚠️  grades: {e}")


def main():
    print("=== Migrating Google Sheets → Supabase Database ===\n")
    sb = get_supabase()
    gc = get_sheets_client()
    migrate_settings(gc, sb)
    migrate_students(gc, sb)
    migrate_weeks(gc, sb)
    migrate_grades(gc, sb)
    print("\n=== Migration complete ===")


if __name__ == "__main__":
    main()
