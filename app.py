import os
import json
import time
from datetime import datetime

import gradio as gr

from src.pipeline import run_query

# === 解决 Gradio 502：代理拦截 localhost 回调 ===
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"
for k in ["HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy"]:
    os.environ.pop(k, None)

DOC_REGISTRY_PATH = "docs/doc_registry.json"
LOG_DIR = "logs/gradio_sessions"
os.makedirs(LOG_DIR, exist_ok=True)


def load_doc_ids():
    if not os.path.exists(DOC_REGISTRY_PATH):
        return ["default"]
    with open(DOC_REGISTRY_PATH, "r", encoding="utf-8") as f:
        reg = json.load(f)
    # 下拉显示 doc_id，值也是 doc_id
    return list(reg.keys()) if reg else ["default"]


def citations_to_markdown(citations):
    if not citations:
        return "（无引用）"

    lines = []
    for i, c in enumerate(citations, start=1):
        # 兼容两种字段名（你目前两边都有出现）
        cite_id = c.get("cite_id", i)
        doc_id = c.get("doc_id", "N/A")
        page = c.get("page", "N/A")
        chunk_id = c.get("chunk_id", "N/A")
        faiss_score = c.get("faiss_score", None)
        rerank_score = c.get("rerank_score", None)
        link = c.get("link", c.get("jump_link", "N/A"))
        snippet = c.get("snippet", "")
        if not snippet and c.get("text"):
            snippet = c["text"].strip().replace("\n", " ")
            snippet = snippet[:120] + ("..." if len(snippet) > 120 else "")

        score_part = []
        if faiss_score is not None:
            score_part.append(f"faiss={faiss_score:.4f}")
        if rerank_score is not None:
            score_part.append(f"rerank={rerank_score:.4f}")

        score_str = (" (" + ", ".join(score_part) + ")") if score_part else ""
        lines.append(f"**[{cite_id}] {doc_id} p{page} chunk{chunk_id}**{score_str}")
        lines.append(f"- 摘要：{snippet}")
        lines.append(f"- 跳页：{link}")
        lines.append("")
    return "\n".join(lines)


def timings_to_markdown(timings: dict):
    if not timings:
        return "（无耗时信息）"
    order = ["retrieve_sec", "rerank_sec", "generate_sec", "judge_sec", "rag_sec"]
    lines = []
    total = 0.0
    for k in order:
        if k in timings:
            v = float(timings[k])
            total += v
            lines.append(f"- {k}: {v:.2f}s")
    # 加上其它未列出的键
    for k, v in timings.items():
        if k not in order:
            try:
                vv = float(v)
                total += 0.0
                lines.append(f"- {k}: {vv:.2f}s")
            except:
                lines.append(f"- {k}: {v}")
    lines.append(f"- total(approx): {total:.2f}s")
    return "\n".join(lines)


def save_session(record: dict):
    log_path = os.path.join(LOG_DIR, datetime.now().strftime("%Y%m%d") + ".jsonl")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def on_ask(doc_id, question, topk, use_rerank, use_judge, sim_threshold, chat_history):
    question = (question or "").strip()
    if not question:
        return chat_history, "请输入问题。", "（无引用）", "（无可信度）", "（无耗时）"

    t0 = time.time()
    answer, citations, confidence, timings = run_query(
        doc_id=doc_id,
        question=question,
        topk=int(topk),
        use_rerank=bool(use_rerank),
        use_judge=bool(use_judge),
        sim_threshold=float(sim_threshold),
    )
    t_total = time.time() - t0

    # 更新聊天
    chat_history = (chat_history or []) + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]

    # 展示区
    cite_md = citations_to_markdown(citations)
    conf_md = "（未启用可信度）" if confidence is None else ("```json\n" + json.dumps(confidence, ensure_ascii=False, indent=2) + "\n```")
    time_md = timings_to_markdown({**timings, "total_wall_sec": t_total})

    # 落盘
    save_session({
        "time": datetime.now().isoformat(),
        "doc_id": doc_id,
        "question": question,
        "answer": answer,
        "params": {
            "topk": int(topk),
            "use_rerank": bool(use_rerank),
            "use_judge": bool(use_judge),
            "sim_threshold": float(sim_threshold),
        },
        "citations": citations,
        "confidence": confidence,
        "timings": {**timings, "total_wall_sec": t_total},
    })

    status = f"完成。已写入 logs/gradio_sessions/{datetime.now().strftime('%Y%m%d')}.jsonl"
    return chat_history, status, cite_md, conf_md, time_md


def on_clear():
    return [], "已清空。", "（无引用）", "（无可信度）", "（无耗时）"


def build_ui():
    doc_ids = load_doc_ids()
    

    with gr.Blocks(title="CiteRAG Demo") as demo:
        gr.Markdown("# CiteRAG：可引用的中文 PDF RAG + 可信度自检")

        with gr.Row():
            with gr.Column(scale=1):
                doc_id = gr.Dropdown(choices=doc_ids, value=doc_ids[0], label="选择文档 doc_id")
                topk = gr.Slider(1, 10, value=3, step=1, label="TopK")
                use_rerank = gr.Checkbox(value=False, label="Use reranker（重排）")
                use_judge = gr.Checkbox(value=True, label="Use confidence judge（可信度自检）")

                ask_btn = gr.Button("Ask", variant="primary")
                clear_btn = gr.Button("Clear")

                status = gr.Textbox(label="状态", value="就绪。", interactive=False)

            with gr.Column(scale=2):
                chat = gr.Chatbot(label="对话", height=320, type="messages")

                with gr.Accordion("Citations（引用）", open=True):
                    cite_md = gr.Markdown("（无引用）")

                with gr.Accordion("Confidence（可信度）", open=True):
                    conf_md = gr.Markdown("（无可信度）")

                with gr.Accordion("Timings（耗时）", open=False):
                    time_md = gr.Markdown("（无耗时）")

        ask_btn.click(
            fn=on_ask,
            inputs=[doc_id, question, topk, use_rerank, use_judge, sim_threshold, chat],
            outputs=[chat, status, cite_md, conf_md, time_md],
        )

        # 上面 inputs 里用了一个隐藏 Textbox 占位（Gradio 需要组件）
        # 我们用下面这个显式 question 输入替换它：
        # ——做法：再建一个真正的 question 输入，并重新绑定 click

    return demo


# 为了让 question 输入在左侧更直观：重建 UI（更简洁）
def build_ui_v2():
    doc_ids = load_doc_ids()

    with gr.Blocks(title="CiteRAG Demo") as demo:
        gr.Markdown("# CiteRAG：可引用的中文 PDF RAG + 可信度自检")

        with gr.Row():
            with gr.Column(scale=1):
                doc_id = gr.Dropdown(choices=doc_ids, value=doc_ids[0], label="选择文档 doc_id")
                question = gr.Textbox(label="问题", placeholder="输入你的问题，然后点击 Ask", lines=3)
                topk = gr.Slider(1, 10, value=3, step=1, label="TopK")
                sim_threshold = gr.Slider(0.30, 0.70, value=0.52, step=0.01, label="Judge sim_threshold（越大越严格）")
                use_rerank = gr.Checkbox(value=False, label="Use reranker（重排）")
                use_judge = gr.Checkbox(value=True, label="Use confidence judge（可信度自检）")

                ask_btn = gr.Button("Ask", variant="primary")
                clear_btn = gr.Button("Clear")
                status = gr.Textbox(label="状态", value="就绪。", interactive=False)

            with gr.Column(scale=2):
                chat = gr.Chatbot(label="对话", height=320)

                with gr.Accordion("Citations（引用）", open=True):
                    cite_md = gr.Markdown("（无引用）")

                with gr.Accordion("Confidence（可信度）", open=True):
                    conf_md = gr.Markdown("（无可信度）")

                with gr.Accordion("Timings（耗时）", open=False):
                    time_md = gr.Markdown("（无耗时）")

        ask_btn.click(
            fn=on_ask,
            inputs=[doc_id, question, topk, use_rerank, use_judge, sim_threshold, chat],
            outputs=[chat, status, cite_md, conf_md, time_md],
        )
        clear_btn.click(fn=on_clear, inputs=[], outputs=[chat, status, cite_md, conf_md, time_md])

    return demo


if __name__ == "__main__":
    demo = build_ui_v2()
    demo.launch(server_name="127.0.0.1", server_port=7861)