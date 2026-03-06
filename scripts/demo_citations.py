import json
import os
from urllib.parse import quote

PDF_PAGE_OFFSET = 1  # 很多阅读器 page=1 表示第一页；如果你发现跳页偏一页，就改成 0

def load_registry(path="docs/doc_registry.json"):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def to_file_url(pdf_path: str, page_1based: int) -> str:
    # Windows 路径转 file:/// URL，并带 #page=
    # 例：E:/a/b.pdf -> file:///E:/a/b.pdf#page=10
    p = pdf_path.replace("\\", "/")
    # 对路径做 URL 编码，避免空格等字符问题
    p = quote(p, safe=":/")
    return f"file:///{p}#page={page_1based}"

def build_citations(evidences, registry):
    """evidences: list of dict, each has doc_id/page/chunk_id/text/faiss_score/rerank_score"""
    citations = []
    for i, ev in enumerate(evidences, start=1):
        doc_id = ev["doc_id"]
        page = int(ev["page"])
        chunk_id = ev["chunk_id"]
        text = ev.get("text", "")

        snippet = text.strip().replace("\n", " ")
        snippet = snippet[:80] + ("..." if len(snippet) > 80 else "")

        pdf_path = registry.get(doc_id)
        link = "N/A"
        if pdf_path:
            link = to_file_url(pdf_path, page + PDF_PAGE_OFFSET)

        citations.append({
            "cite_id": i,
            "doc_id": doc_id,
            "page": page,
            "chunk_id": chunk_id,
            "snippet": snippet,
            "faiss_score": ev.get("faiss_score"),
            "rerank_score": ev.get("rerank_score"),
            "link": link
        })
    return citations

def format_answer_with_citations(answer_lines, citations, default_cite_ids=None):
    """最简单策略：每条要点都挂同一组引用编号"""
    if default_cite_ids is None:
        default_cite_ids = [c["cite_id"] for c in citations[:3]]  # 默认 top3

    cite_str = "".join([f"[{i}]" for i in default_cite_ids])
    out = []
    out.append("回答：")
    for idx, line in enumerate(answer_lines, start=1):
        out.append(f"{idx}) {line} {cite_str}")

    out.append("\n引用：")
    for c in citations:
        score_str = []
        if c["rerank_score"] is not None:
            score_str.append(f"rerank={c['rerank_score']:.4f}")
        if c["faiss_score"] is not None:
            score_str.append(f"faiss={c['faiss_score']:.4f}")
        score_show = " / ".join(score_str) if score_str else "score=N/A"

        out.append(f"[{c['cite_id']}] {c['doc_id']} p{c['page']} chunk{c['chunk_id']}  ({score_show})")
        out.append(f"    摘要：{c['snippet']}")
        out.append(f"    打开：{c['link']}")
    return "\n".join(out)

def main():
    registry = load_registry()

    # 这里模拟 3 条“检索到的证据”（你之后会把它换成真实 RAG 的 topK）
    evidences = [
        {"doc_id": "os_tutorial", "page": 374, "chunk_id": 12,
         "text": "进程调度是操作系统在多个就绪进程中选择一个运行的机制，涉及调度策略与切换开销……",
         "faiss_score": 0.63, "rerank_score": 9.82},
        {"doc_id": "co", "page": 179, "chunk_id": 7,
         "text": "Cache 是一种位于 CPU 与主存之间的高速存储结构，用于利用局部性原理提升访问速度……",
         "faiss_score": 0.59, "rerank_score": 8.11},
        {"doc_id": "os_tutorial", "page": 180, "chunk_id": 3,
         "text": "时间片轮转算法适合分时系统，通过为每个进程分配固定时间片实现公平性……",
         "faiss_score": 0.55, "rerank_score": 7.50},
    ]

    citations = build_citations(evidences, registry)

    # 模拟“回答正文”（真实情况来自 LLM 输出）
    answer_lines = [
        "进程调度决定了 CPU 在多个就绪进程之间如何分配执行权。",
        "常见策略包括先来先服务、短作业优先、时间片轮转等。",
        "调度需要在吞吐、公平、响应时间等指标之间权衡。"
    ]

    text = format_answer_with_citations(answer_lines, citations)
    print(text)

if __name__ == "__main__":
    main()