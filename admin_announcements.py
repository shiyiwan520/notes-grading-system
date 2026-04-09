"""
admin_announcements.py — 系統公告分頁
"""
import streamlit as st
import storage


def render():
    st.subheader("Announcements / 系統公告")
    st.caption("Announcements appear at the top of the student-facing pages. / 公告會顯示在學生端頁面頂部。")

    # 現有公告
    all_ann = storage.get_announcements()
    if all_ann:
        st.markdown("**Active announcements / 目前公告：**")
        for ann in all_ann:
            col1, col2 = st.columns([5, 1])
            with col1:
                st.info(f"📢 {ann['content']}  \n*{ann.get('posted_at','')}*")
            with col2:
                st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)
                if st.button("Remove / 移除", key=f"rm_{ann['id']}"):
                    storage.deactivate_announcement(ann["id"])
                    st.rerun()
    else:
        st.info("No active announcements. / 目前無公告。")

    st.divider()

    # 新增公告
    st.markdown("**Post new announcement / 發布新公告：**")
    new_ann = st.text_area(
        "Announcement content / 公告內容",
        placeholder="e.g. Week 03 deadline extended to Oct 20. / 第3週截止日延至10月20日。",
        height=100
    )
    if st.button("Post / 發布", type="primary"):
        if new_ann.strip():
            storage.save_announcement(new_ann.strip())
            st.success("Announcement posted! / 公告已發布！")
            st.rerun()
        else:
            st.error("Please enter announcement content. / 請輸入公告內容。")
