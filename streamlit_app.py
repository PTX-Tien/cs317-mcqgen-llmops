"""
streamlit_app.py — MCQGen Web UI
Chạy: streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
"""
import streamlit as st
import requests, time, json

API_URL = "http://localhost:7860"

CHAPTERS = {
    "ch02": "Ch02 — Popular Libraries (NumPy, Pandas)",
    "ch03": "Ch03 — Pipeline & EDA",
    "ch04": "Ch04 — Tiền xử lý dữ liệu",
    "ch05": "Ch05 — Đánh giá mô hình",
    "ch06": "Ch06 — Unsupervised Learning",
    "ch07a": "Ch07a — Regression",
    "ch07b": "Ch07b — Classification",
    "ch08": "Ch08 — Deep Learning & CNN",
    "ch09": "Ch09 — Parameter Tuning",
    "ch10": "Ch10 — Ensemble Models",
    "ch11": "Ch11 — Model Deployment",
}

TOPIC_SUGGESTIONS = {
    "ch04": ["Missing Data", "Outlier Detection", "Feature Selection", "SimpleImputer sklearn"],
    "ch07b": ["Decision Trees", "Logistic Regression", "SVM"],
    "ch08": ["CNN Neural Networks", "Convolution Layer", "Pooling Layer"],
    "ch10": ["Random Forest", "Boosting", "Bagging"],
}

st.set_page_config(page_title="MCQGen CS116", page_icon="📝", layout="wide")
st.title("📝 Automatic MCQ Generation — CS116")
st.caption("Hệ thống sinh câu hỏi trắc nghiệm tự động từ slide + transcript bài giảng")

# ── Sidebar: Config ───────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Cấu hình đề thi")

    output_name = st.text_input("Tên đề thi", value="exam_01")
    difficulty = st.selectbox("Độ khó", ["G1", "G2", "G3"], index=1)

    st.subheader("Chọn topic")
    topics = []
    for i in range(1, 4):
        with st.expander(f"Topic {i}", expanded=(i == 1)):
            chapter = st.selectbox(
                "Chapter", list(CHAPTERS.keys()),
                format_func=lambda x: CHAPTERS[x],
                key=f"ch_{i}"
            )
            suggestions = TOPIC_SUGGESTIONS.get(chapter, [""])
            topic = st.text_input(
                "Topic (tên cụ thể)",
                value=suggestions[0] if suggestions else "",
                key=f"topic_{i}"
            )
            n_q = st.slider("Số câu", 1, 5, 2, key=f"n_{i}")

            if topic.strip():
                topics.append({
                    "topic_id": f"t{i}_{chapter}",
                    "chapter_id": chapter,
                    "topic": topic.strip(),
                    "difficulty": difficulty,
                    "n": n_q
                })

    total_q = sum(t["n"] for t in topics)
    st.info(f"Tổng: **{total_q} câu hỏi** từ {len(topics)} topic")

    generate_btn = st.button(
        "🚀 Sinh câu hỏi", type="primary",
        disabled=(len(topics) == 0)
    )

# ── Main: Generation + Results ────────────────────────────────────
if generate_btn and topics:
    st.divider()

    # Submit job
    try:
        resp = requests.post(
            f"{API_URL}/generate",
            json={"topics": topics, "output_name": output_name},
            timeout=10
        )
        data = resp.json()
        task_id = data["task_id"]
        st.success(f"✅ Job submitted | Task ID: `{task_id}`")
    except Exception as e:
        st.error(f"❌ Không thể kết nối API: {e}")
        st.stop()

    # Poll progress
    progress_bar = st.progress(0)
    status_text  = st.empty()
    est_text     = st.empty()

    start_time = time.time()
    while True:
        try:
            sr = requests.get(f"{API_URL}/status/{task_id}", timeout=5).json()
        except:
            time.sleep(3)
            continue

        state    = sr.get("state", "")
        progress = sr.get("progress", 0)
        step     = sr.get("step", "")
        elapsed  = time.time() - start_time

        progress_bar.progress(progress / 100)
        status_text.markdown(f"**Trạng thái:** `{state}` | **Bước:** `{step}`")
        est_text.caption(f"⏱ Đã chạy: {elapsed:.0f}s")

        if state == "success":
            progress_bar.progress(1.0)
            break
        elif state == "failed":
            st.error(f"❌ Pipeline thất bại: {sr.get('error','')}")
            st.stop()

        time.sleep(4)

    # Get results
    try:
        rr   = requests.get(f"{API_URL}/results/{task_id}", timeout=10).json()
        mcqs = rr.get("mcqs", [])
    except Exception as e:
        st.error(f"Không lấy được kết quả: {e}")
        st.stop()

    elapsed = time.time() - start_time
    st.success(
        f"✅ Hoàn thành! **{rr.get('accepted',0)} câu hỏi** "
        f"trong **{elapsed:.0f}s ({elapsed/60:.1f} phút)**"
    )
    st.divider()

    # Hiển thị MCQs
    st.subheader(f"📋 Kết quả — {len(mcqs)} câu hỏi")

    for i, mcq in enumerate(mcqs, 1):
        with st.expander(
            f"**Câu {i}** | {mcq.get('topic','')} | "
            f"Score: {mcq.get('evaluation',{}).get('quality_score',0):.2f}",
            expanded=(i <= 3)
        ):
            st.markdown(f"**{mcq.get('question_text','')}**")
            st.divider()
            cols = st.columns(2)
            correct = mcq.get("correct_answers", [])
            for j, (k, v) in enumerate(mcq.get("options", {}).items()):
                col = cols[j % 2]
                if k in correct:
                    col.success(f"✓ **{k}.** {v}")
                else:
                    col.markdown(f"**{k}.** {v}")

            if mcq.get("style_alignment_note"):
                st.caption(f"📌 {mcq['style_alignment_note']}")

    # Export buttons
    st.divider()
    col1, col2, col3 = st.columns(3)

    # JSON
    json_str = json.dumps(mcqs, ensure_ascii=False, indent=2)
    col1.download_button(
        "⬇️ JSON",
        data=json_str,
        file_name=f"{output_name}_mcqs.json",
        mime="application/json",
        use_container_width=True,
    )

    # PDF đề thi (không có đáp án)
    try:
        pdf_resp = requests.get(
            f"{API_URL}/export/pdf/{task_id}?include_answers=false",
            timeout=15
        )
        if pdf_resp.status_code == 200:
            col2.download_button(
                "📄 PDF Đề thi",
                data=pdf_resp.content,
                file_name=f"{output_name}_exam.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
    except Exception as e:
        col2.error(f"PDF error: {e}")

    # PDF có đáp án
    try:
        pdf_ans_resp = requests.get(
            f"{API_URL}/export/pdf/{task_id}?include_answers=true",
            timeout=15
        )
        if pdf_ans_resp.status_code == 200:
            col3.download_button(
                "🔑 PDF Đáp án",
                data=pdf_ans_resp.content,
                file_name=f"{output_name}_answers.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
    except Exception as e:
        col3.error(f"PDF error: {e}")
