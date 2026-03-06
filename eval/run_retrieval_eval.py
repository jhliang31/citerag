import os
import json
import csv
import argparse
from typing import List, Dict, Any

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
from transformers import logging
logging.set_verbosity_error()

SOFT_WINDOW = 1   # 0=Strict only，1=±1页容错
DEFAULT_KS = [1, 3, 5]
DEFAULT_QUESTIONS_PATH = "eval/questions.jsonl"
DEFAULT_OUT_CSV = "reports/retrieval_results.csv"


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index_dir", required=True, help="Directory containing faiss.index and meta.json")
    ap.add_argument("--questions", default=DEFAULT_QUESTIONS_PATH)
    ap.add_argument("--out_csv", default=DEFAULT_OUT_CSV)
    ap.add_argument("--ks", nargs="+", type=int, default=DEFAULT_KS)
    ap.add_argument("--device", default="cuda", help="cuda or cpu")
    ap.add_argument("--model", default=None, help="Override embed model name (default: read from meta.json)")
    ap.add_argument("--soft_window", type=int, default=SOFT_WINDOW)
     # ===== Day11 新增 =====
    ap.add_argument("--use_rerank", action="store_true")
    ap.add_argument("--rerank_model", default="BAAI/bge-reranker-base")
    ap.add_argument("--retrieve_topn", type=int, default=10)
    ap.add_argument("--rerank_batch_size", type=int, default=16)
    return ap.parse_args()


def load_questions(path: str) -> List[Dict[str, Any]]:
    qs = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            if "question" not in obj or "doc_id" not in obj or "gold_pages" not in obj:
                raise ValueError(f"Bad question format at line {line_no}: must have question/doc_id/gold_pages")

            if not isinstance(obj["gold_pages"], list):
                raise ValueError(f"gold_pages must be list at line {line_no}")

            qs.append(obj)
    return qs


def normalize_page(x) -> int:
    return int(x)


def get_hits_for_k(retrieved, gold_doc, gold_pages, k, soft_window: int):
    gold_set = set(gold_pages)

    soft_set = set()
    for gp in gold_pages:
        for t in range(gp - soft_window, gp + soft_window + 1):
            soft_set.add(t)

    strict_hit = 0
    soft_hit = 0

    for item in retrieved[:k]:
        if item.get("doc_id") != gold_doc:
            continue

        p = item.get("page")
        if p is None:
            continue

        try:
            p = int(p)
        except:
            continue

        if p in gold_set:
            strict_hit = 1
        if p in soft_set:
            soft_hit = 1

    return strict_hit, soft_hit


def load_meta(meta_path: str):
    """兼容两种格式：
    1) 旧版：meta.json 是 List[chunk]
    2) 新版：meta.json 是 Dict{..., "chunks": List[chunk], "embed_model":..., "embed_dim":...}
    """
    obj = json.load(open(meta_path, "r", encoding="utf-8"))
    if isinstance(obj, list):
        return {"chunks": obj, "embed_model": None, "embed_dim": None, "normalize": None}
    if isinstance(obj, dict):
        if "chunks" not in obj or not isinstance(obj["chunks"], list):
            raise ValueError("meta.json is dict but missing 'chunks' list")
        return obj
    raise ValueError("meta.json must be a list or dict")


def main():
    args = parse_args()
    os.makedirs(os.path.dirname(args.out_csv) or ".", exist_ok=True)

    index_path = os.path.join(args.index_dir, "faiss.index")
    meta_path = os.path.join(args.index_dir, "meta.json")

    print("Loading FAISS index...")
    index = faiss.read_index(index_path)
    print("Index ntotal:", index.ntotal)

    print("Loading meta...")
    meta_obj = load_meta(meta_path)
    meta_chunks: List[Dict[str, Any]] = meta_obj["chunks"]

    if len(meta_chunks) != index.ntotal:
        print(f"⚠ meta size {len(meta_chunks)} != index.ntotal {index.ntotal} (should match)")

    # doc 分布检查
    doc_counts = {}
    for m in meta_chunks:
        d = m.get("doc_id", "UNKNOWN")
        doc_counts[d] = doc_counts.get(d, 0) + 1
    print("Doc distribution:", doc_counts)

    print("Loading questions...")
    questions = load_questions(args.questions)
    print("Questions:", len(questions))

    # 选 embedding 模型：优先 args.model，其次 meta.json 里的 embed_model
    emb_model = args.model or meta_obj.get("embed_model")
    if not emb_model:
        raise ValueError("No embedding model specified. Pass --model or rebuild index with meta.embed_model.")
    print("Loading embedding model:", emb_model)

    model = SentenceTransformer(emb_model, device=args.device)

    reranker = None
    if args.use_rerank:
        from sentence_transformers import CrossEncoder
        print("Loading reranker:", args.rerank_model)
        reranker = CrossEncoder(args.rerank_model, device=args.device)

    max_k = max(args.ks)

    # 统计 hit
    hit_counts_strict = {k: 0 for k in args.ks}
    hit_counts_soft = {k: 0 for k in args.ks}

    rows = []

    for q in tqdm(questions, desc="Evaluating"):
        question = q["question"]
        gold_doc = q["doc_id"]
        gold_pages = [normalize_page(p) for p in q["gold_pages"]]

        qvec = model.encode([question], normalize_embeddings=True).astype(np.float32)

        # 维度强校验（如果 meta 里有 embed_dim）
        meta_dim = meta_obj.get("embed_dim")
        if meta_dim is not None and int(qvec.shape[1]) != int(meta_dim):
            raise ValueError(f"Embedding dim mismatch: query {qvec.shape[1]} vs meta {meta_dim}")

        # 先粗召回 retrieve_topn（至少 >= max_k）
        topn = max(args.retrieve_topn, max_k)
        scores, ids = index.search(qvec, topn)

        retrieved_meta = [meta_chunks[int(i)] for i in ids[0]]

        # rerank
        if reranker is not None:
            pairs = [(question, r.get("text", "")) for r in retrieved_meta]
            rr_scores = reranker.predict(pairs, batch_size=args.rerank_batch_size)

            retrieved_meta = [
                r for r, s in sorted(
                    zip(retrieved_meta, rr_scores),
                    key=lambda x: x[1],
                    reverse=True
                )
            ]

        row = {
            "question": question,
            "gold_doc": gold_doc,
            "gold_pages": gold_pages,
        }

        row["retrieved"] = [
            {
                "doc_id": r.get("doc_id"),
                "page": r.get("page"),
                "chunk_id": r.get("chunk_id"),
                "score": float(s),
            }
            for r, s in zip(retrieved_meta, scores[0])
        ]

        for k in args.ks:
            strict_hit, soft_hit = get_hits_for_k(
                retrieved_meta, gold_doc, gold_pages, k, args.soft_window
            )
            row[f"hit_strict@{k}"] = strict_hit
            row[f"hit_soft@{k}"] = soft_hit
            hit_counts_strict[k] += strict_hit
            hit_counts_soft[k] += soft_hit

        rows.append(row)

    # 写 CSV
    with open(args.out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = (
            ["question", "gold_doc", "gold_pages"]
            + [f"hit_strict@{k}" for k in args.ks]
            + [f"hit_soft@{k}" for k in args.ks]
            + ["retrieved_topk"]
        )
        writer.writerow(header)

        for r in rows:
            writer.writerow([
                r["question"],
                r["gold_doc"],
                json.dumps(r["gold_pages"], ensure_ascii=False),
                *[r[f"hit_strict@{k}"] for k in args.ks],
                *[r[f"hit_soft@{k}"] for k in args.ks],
                json.dumps(r["retrieved"], ensure_ascii=False),
            ])

    n = len(questions)
    print("\n==== Retrieval Eval Summary ====")
    print("\n==== Strict Recall ====")
    for k in args.ks:
        recall = hit_counts_strict[k] / n
        print(f"Recall@{k}: {recall:.3f} ({hit_counts_strict[k]}/{n})")

    print(f"\n==== Soft Recall (±{args.soft_window} page) ====")
    for k in args.ks:
        recall = hit_counts_soft[k] / n
        print(f"Recall@{k}: {recall:.3f} ({hit_counts_soft[k]}/{n})")

    print(f"\nSaved: {args.out_csv}")


if __name__ == "__main__":
    main()