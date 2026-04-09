"""
admin_dashboard.py — 後台 Dashboard 分頁
統計摘要 + 缺交名單 + 成績圖表
"""

import streamlit as st
import pandas as pd
import storage


def render(semester: str):
    st.subheader(f"Dashboard — {semester or 'No semester selected'}")

    if not semester:
        st.info("Please set the current semester in Settings.")
        return

    records = storage.load_all_records(semester)
    students = storage.get_students(semester)
    open_weeks = storage.get_all_weeks(semester)

    if not records and not students:
        st.info("No data yet for this semester.")
        return

    # ── 統計卡片 ──────────────────────────────────────────────
    total_students = len(students)
    total_submissions = len(records)
    needs_review = sum(1 for r in records if str(r.get("needs_review", "")).lower() in ("true","1"))
    scan_only = sum(1 for r in records if str(r.get("scan_only", "")).lower() in ("true","1"))
    late_count = sum(1 for r in records if str(r.get("is_late", "")).lower() in ("true","1"))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Students / 學生", total_students)
    c2.metric("Submissions / 繳交", total_submissions)
    c3.metric("⚠️ Review / 待複查", needs_review)
    c4.metric("📄 Scan only", scan_only)
    c5.metric("📨 Late / 補交", late_count)

    st.divider()

    # ── 缺交名單（按週次）────────────────────────────────────
    st.subheader("Missing Submissions / 缺交名單")

    opened_weeks = [w for w in open_weeks if str(w.get("open", "")).lower() in ("true","1")]
    if not opened_weeks:
        st.info("No weeks have been opened yet.")
    else:
        for w in sorted(opened_weeks, key=lambda x: x.get("week", "")):
            week = str(w.get("week", ""))
            submitted_ids = {
                r["student_id"].upper() for r in records
                if str(r.get("week")) == week
            }
            missing = [s for s in students if s["student_id"].upper() not in submitted_ids]

            label = f"Week {week} — {len(submitted_ids)}/{total_students} submitted"
            if missing:
                label += f"  ⚠️ {len(missing)} missing"

            with st.expander(label):
                if not missing:
                    st.success("All students have submitted! / 全員已繳交！")
                else:
                    missing_df = pd.DataFrame(missing)[["student_id", "name"]]
                    missing_df.columns = ["Student ID / 學號", "Name / 姓名"]
                    st.dataframe(missing_df, use_container_width=True, hide_index=True)

    st.divider()

    # ── 成績分佈圖表 ──────────────────────────────────────────
    st.subheader("Score Distribution / 成績分佈")

    if not records:
        st.info("No graded submissions yet.")
        return

    df = pd.DataFrame(records)

    # 計算每週分數（使用 final_score 優先，否則 ai_score）
    def effective_score(row):
        fs = str(row.get("final_score", "")).strip()
        ai = str(row.get("ai_score", "")).strip()
        try:
            return int(fs) if fs else int(ai)
        except ValueError:
            return None

    df["score"] = df.apply(effective_score, axis=1)
    df_valid = df.dropna(subset=["score"])

    if df_valid.empty:
        st.info("No scores to display yet.")
        return

    # 各週平均分數折線圖
    week_avg = (
        df_valid.groupby("week")["score"]
        .agg(["mean", "count"])
        .reset_index()
        .sort_values("week")
    )
    week_avg.columns = ["Week", "Average Score", "Count"]
    week_avg["Week"] = "Week " + week_avg["Week"].astype(str)
    week_avg["Average Score"] = week_avg["Average Score"].round(2)

    st.markdown("**Weekly Average Score / 各週平均分數**")
    st.line_chart(week_avg.set_index("Week")["Average Score"])

    # 全體分數分佈長條圖
    st.markdown("**Overall Score Distribution / 全體分數分佈**")
    score_counts = df_valid["score"].value_counts().sort_index()
    score_df = pd.DataFrame({
        "Score / 分數": score_counts.index.astype(str),
        "Count / 人數": score_counts.values
    })
    st.bar_chart(score_df.set_index("Score / 分數"))

    st.divider()

    # ── 匯出 CSV ──────────────────────────────────────────────
    st.subheader("Export / 匯出")
    export_df = df[["student_id", "name", "week", "ai_score", "final_score",
                     "ai_justification", "is_late", "needs_review", "released", "submitted_at"]].copy()
    export_df.columns = [
        "學號", "姓名", "週次", "AI分數", "老師最終分數",
        "AI評語", "補交", "需複查", "已公開", "繳交時間"
    ]
    csv = export_df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        "📥 Download CSV / 下載全班成績",
        data=csv,
        file_name=f"grades_{semester}.csv",
        mime="text/csv",
        use_container_width=True
    )
