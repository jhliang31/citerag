import time
from typing import Tuple, List, Dict, Optional

# 直接用你已经模块化成功的函数
from scripts.rag_answer import retrieve_topk, generate_with_chunks
from sentence_transformers import CrossEncoder
from scripts.rag_answer import load_resources  # 复用缓存的 llm/tokenizer
from scripts.rag_with_confidence import judge_with_confidence

# ===== 全局缓存 reranker（避免重复加载）=====
_RERANKER = None

def get_reranker(model_name="BAAI/bge-reranker-base", device="cuda"):
    global _RERANKER
    if _RERANKER is None:
        print("Loading reranker:", model_name)
        _RERANKER = CrossEncoder(model_name, device=device)
    return _RERANKER


def rerank_chunks(question, chunks, batch_size=4):
    """
    输入：
        question: str
        chunks: List[dict] (必须包含 text 字段)
    输出：
        按 rerank_score 降序排列后的 chunks
    """
    if not chunks:
        return chunks

    reranker = get_reranker()

    pairs = [(question, c.get("text", "")) for c in chunks]
    scores = reranker.predict(pairs, batch_size=batch_size)

    for c, s in zip(chunks, scores):
        c["rerank_score"] = float(s)

    chunks = sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
    return chunks

def run_query(
    doc_id: str,
    question: str,
    topk: int = 3,
    use_rerank: bool = True,
    use_judge: bool = False,
    recall_k: int = 5,
    sim_threshold: float = 0.52
):
    timings = {}

    # ===== 1️⃣ 先召回 recall_k =====
    t0 = time.time()
    candidates = retrieve_topk(doc_id, question, topn=recall_k)
    timings["retrieve_sec"] = time.time() - t0

    # ===== 2️⃣ rerank（可选）=====
    if use_rerank:
        t0 = time.time()
        candidates = rerank_chunks(question, candidates)
        timings["rerank_sec"] = time.time() - t0

    # ===== 3️⃣ 取 topk =====
    top_chunks = candidates[:topk]

    # ===== 生成 =====
    t_gen0 = time.time()
    answer = generate_with_chunks(question, top_chunks)
    timings["generate_sec"] = time.time() - t_gen0

    # ===== judge（可选）=====
    confidence = None
    if use_judge:
        t_j0 = time.time()
        R = load_resources()
        confidence = judge_with_confidence(
            question=question,
            answer=answer,
            top_chunks=top_chunks,
            model=R["llm"],
            tokenizer=R["tokenizer"],
            sim_threshold=sim_threshold,
        )
        timings["judge_sec"] = time.time() - t_j0

    

    return answer, top_chunks, confidence, timings