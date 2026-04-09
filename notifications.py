"""
notifications.py — Email 每日摘要通知模組
使用 Gmail SMTP，當天有繳交才寄
"""

import streamlit as st
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date
from typing import Dict
import storage


def notify_new_submission(record: Dict):
    """
    每次有新繳交時呼叫。
    利用 Google Sheets 記錄「今天是否已寄過」，避免每次繳交都寄一封。
    改為：當天第一筆繳交觸發，記錄「今日待寄摘要」，
    實際寄送在老師手動點「寄送今日摘要」或透過排程觸發。
    簡化版：直接在繳交時寄送摘要（適合35人小班）。
    """
    teacher_email = storage.get_settings().get("teacher_email", "")
    if not teacher_email:
        return  # 老師未設定信箱，靜默不寄

    today_str = date.today().strftime("%Y-%m-%d")
    last_sent = storage.get_settings().get("last_email_sent", "")

    if last_sent == today_str:
        return  # 今天已寄過，不重複寄

    # 收集今日繳交摘要
    semester = storage.get_settings().get("current_semester", "")
    all_records = storage.load_all_records(semester)
    today_records = [r for r in all_records
                     if r.get("submitted_at", "").startswith(today_str)]

    if not today_records:
        return

    # 計算缺交名單（以目前開放的最新週次為準）
    open_weeks = storage.get_open_weeks(semester)
    missing_info = ""
    if open_weeks:
        latest_week = sorted(open_weeks, key=lambda w: w["week"])[-1]["week"]
        students = storage.get_students(semester)
        submitted_ids = {r["student_id"].upper() for r in all_records
                         if str(r.get("week")) == str(latest_week)}
        missing = [s["name"] for s in students
                   if s["student_id"].upper() not in submitted_ids]
        if missing:
            missing_info = f"\n未繳名單（Week {latest_week}，共 {len(missing)} 人）：\n" + "、".join(missing[:20])
            if len(missing) > 20:
                missing_info += f" ...等共 {len(missing)} 人"

    needs_review_count = sum(1 for r in today_records
                             if str(r.get("needs_review", "")).lower() in ("true", "1"))
    scan_count = sum(1 for r in today_records
                     if str(r.get("scan_only", "")).lower() in ("true", "1"))

    subject = f"[Notes System] Daily Summary — {today_str}"
    body = f"""Daily Submission Summary / 今日繳交摘要
Date / 日期：{today_str}
Semester / 學期：{semester}

Today's submissions / 今日繳交：{len(today_records)} 份
AI graded / 完成評分：{len(today_records) - needs_review_count} 份
Needs manual review / 需人工複查：{needs_review_count} 份
Scanned PDFs / 掃描版 PDF：{scan_count} 份
{missing_info}

Please visit the admin panel to review:
請前往後台查看：{st.secrets.get("APP_URL", "https://your-app.streamlit.app")}

---
This is an automated message from the Notes Submission System.
"""
    _send_email(teacher_email, subject, body)

    # 記錄今天已寄
    storage.save_setting("last_email_sent", today_str)


def _send_email(to_email: str, subject: str, body: str):
    """使用 Gmail SMTP 寄送"""
    try:
        gmail_user = st.secrets.get("GMAIL_USER", os.getenv("GMAIL_USER", ""))
        gmail_password = st.secrets.get("GMAIL_APP_PASSWORD", os.getenv("GMAIL_APP_PASSWORD", ""))

        if not gmail_user or not gmail_password:
            return  # 未設定 Gmail 憑證，靜默略過

        msg = MIMEMultipart()
        msg["From"] = gmail_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(gmail_user, gmail_password)
            smtp.send_message(msg)
    except Exception:
        pass  # Email 失敗不影響主系統
