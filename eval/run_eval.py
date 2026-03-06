import os
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from src.pipeline import run_query


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVAL_FILE = PROJECT_ROOT / "eval" / "questions.jsonl"
REPORTS_DIR = PROJECT_ROOT / "reports"
RESULTS_CSV = REPORTS_DIR / "eval_results.csv"
SUMMARY_JSON = REPORTS_DIR / "eval_summary.json"
SUMMARY_MD = REPORTS_DIR / "eval_summary.md"


# =========================
# 可调参数（先写死，后面再做命令行）
# =========================
DEFAULT_TOPK = 5
DEFAULT_USE_RERANK = True
DEFAULT_USE_JUDGE = True
DEFAULT_SIM_THRESHOLD = 0.52


def load_questions(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                rows.append(obj)
            except json.JSONDecodeError as e:
                raise ValueError(f"questions.jsonl 第 {line_no} 行 JSON 解析失败: {e}")
    return rows


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def safe_str(x: Any, default: str = "") -> str:
    if x is None:
        return default
    return str(x)


def normalize_page_list(pages: Any) -> List[int]:
    if pages is None:
        return []
    if isinstance(pages, list):
        out = []
        for p in pages:
            try:
                out.append(int(p))
            except Exception:
                continue
        return out
    return []


def extract_citations(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    citations = result.get("citations", [])
    if citations is None:
        return []
    if isinstance(citations, list):
        return citations
    return []


def extract_retrieved_pages(citations: List[Dict[str, Any]], target_doc_id: str = None) -> List[int]:
    pages = []
    for c in citations:
        doc_id = c.get("doc_id")
        page = c.get("page")
        if target_doc_id is not None and doc_id != target_doc_id:
            continue
        try:
            if page is not None:
                pages.append(int(page))
        except Exception:
            continue
    # 去重并保持升序，便于看结果
    return sorted(set(pages))


def hit_at_k(citations: List[Dict[str, Any]], gold_doc_id: str, gold_pages: List[int], k: int) -> int:
    """
    strict recall@k 的逐题判定：
    前 k 个 citation 中，只要存在一个 citation 同时满足：
    - doc_id == gold_doc_id
    - page in gold_pages
    则记为 1，否则为 0
    """
    if not gold_pages:
        return 0

    topk = citations[:k]
    gold_pages_set = set(int(p) for p in gold_pages)

    for c in topk:
        doc_id = c.get("doc_id")
        page = c.get("page")
        try:
            page = int(page)
        except Exception:
            continue

        if doc_id == gold_doc_id and page in gold_pages_set:
            return 1
    return 0


def extract_confidence_fields(result: Dict[str, Any]) -> Dict[str, Any]:
    conf = result.get("confidence", {})
    if not isinstance(conf, dict):
        conf = {}

    return {
        "supported": safe_str(conf.get("supported", "")),
        "coverage": safe_float(conf.get("coverage", math.nan), math.nan),
        "confidence_level": safe_str(conf.get("confidence_level", "")),
        "unsupported_points_count": len(conf.get("unsupported_points", [])) if isinstance(conf.get("unsupported_points"), list) else 0,
        "coverage_map_count": len(conf.get("coverage_map", [])) if isinstance(conf.get("coverage_map"), list) else 0,
        "judge_reason": safe_str(conf.get("reason", "")),
    }


def extract_timing_fields(result: Dict[str, Any]) -> Dict[str, Any]:
    timings = result.get("timings", {})
    if not isinstance(timings, dict):
        timings = {}

    return {
        "retrieve_sec": safe_float(timings.get("retrieve_sec", 0.0)),
        "rerank_sec": safe_float(timings.get("rerank_sec", 0.0)),
        "generate_sec": safe_float(timings.get("generate_sec", 0.0)),
        "judge_sec": safe_float(timings.get("judge_sec", 0.0)),
    }


def summarize_results(df: pd.DataFrame) -> Dict[str, Any]:
    def mean_col(col: str) -> float:
        if col not in df.columns or len(df) == 0:
            return 0.0
        return float(df[col].fillna(0).mean())

    def avg_col(col: str) -> float:
        if col not in df.columns or len(df) == 0:
            return 0.0
        return float(df[col].fillna(0).mean())

    confidence_dist = {}
    if "confidence_level" in df.columns and len(df) > 0:
        vc = df["confidence_level"].fillna("").value_counts().to_dict()
        confidence_dist = {str(k): int(v) for k, v in vc.items() if str(k) != ""}

    summary = {
        "n_questions": int(len(df)),
        "strict_recall_at_1": round(mean_col("strict_r1"), 4),
        "strict_recall_at_3": round(mean_col("strict_r3"), 4),
        "strict_recall_at_5": round(mean_col("strict_r5"), 4),
        "avg_coverage": round(avg_col("coverage"), 4),
        "avg_retrieve_sec": round(avg_col("retrieve_sec"), 4),
        "avg_rerank_sec": round(avg_col("rerank_sec"), 4),
        "avg_generate_sec": round(avg_col("generate_sec"), 4),
        "avg_judge_sec": round(avg_col("judge_sec"), 4),
        "confidence_level_dist": confidence_dist,
    }
    return summary


def build_summary_markdown(summary: Dict[str, Any], config: Dict[str, Any]) -> str:
    md = []
    md.append("# CiteRAG 自动评测结果摘要")
    md.append("")
    md.append("## 评测配置")
    md.append("")
    md.append(f"- TopK: {config['topk']}")
    md.append(f"- Use Rerank: {config['use_rerank']}")
    md.append(f"- Use Judge: {config['use_judge']}")
    md.append(f"- Sim Threshold: {config['sim_threshold']}")
    md.append("")
    md.append("## 汇总指标")
    md.append("")
    md.append(f"- 题目数：{summary['n_questions']}")
    md.append(f"- Strict Recall@1：{summary['strict_recall_at_1']:.4f}")
    md.append(f"- Strict Recall@3：{summary['strict_recall_at_3']:.4f}")
    md.append(f"- Strict Recall@5：{summary['strict_recall_at_5']:.4f}")
    md.append(f"- 平均 Coverage：{summary['avg_coverage']:.4f}")
    md.append(f"- 平均 Retrieve 时间：{summary['avg_retrieve_sec']:.4f}s")
    md.append(f"- 平均 Rerank 时间：{summary['avg_rerank_sec']:.4f}s")
    md.append(f"- 平均 Generate 时间：{summary['avg_generate_sec']:.4f}s")
    md.append(f"- 平均 Judge 时间：{summary['avg_judge_sec']:.4f}s")
    md.append("")
    md.append("## Confidence Level 分布")
    md.append("")
    if summary["confidence_level_dist"]:
        for k, v in summary["confidence_level_dist"].items():
            md.append(f"- {k}: {v}")
    else:
        md.append("- 无")
    md.append("")
    return "\n".join(md)


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    config = {
        "topk": DEFAULT_TOPK,
        "use_rerank": DEFAULT_USE_RERANK,
        "use_judge": DEFAULT_USE_JUDGE,
        "sim_threshold": DEFAULT_SIM_THRESHOLD,
    }

    questions = load_questions(EVAL_FILE)
    print("DEBUG questions count =", len(questions))
    print("DEBUG first question =", questions[0] if questions else None)

    if not questions:
        raise ValueError(f"{EVAL_FILE} 为空，无法评测。")

    rows = []
    fail_count = 0

    for idx, q in enumerate(questions, start=1):
        qid = q.get("id", idx)
        question = q.get("question", "")
        doc_id = q.get("doc_id", "")
        gold_pages = normalize_page_list(q.get("gold_pages", []))

        print(f"\n[{idx}/{len(questions)}] Running qid={qid}: {question}")

        try:
            # 你的 run_query 固定返回：
            # answer, top_chunks, confidence, timings
            answer, top_chunks, confidence, timings = run_query(
                doc_id=doc_id,
                question=question,
                topk=config["topk"],
                use_rerank=config["use_rerank"],
                use_judge=config["use_judge"],
                sim_threshold=config["sim_threshold"],
            )

            # 防御式处理，避免类型异常
            answer = safe_str(answer)
            citations = top_chunks if isinstance(top_chunks, list) else []
            confidence_obj = confidence if isinstance(confidence, dict) else {}
            timings_obj = timings if isinstance(timings, dict) else {}

            conf_fields = extract_confidence_fields({"confidence": confidence_obj})
            timing_fields = extract_timing_fields({"timings": timings_obj})

            retrieved_pages = extract_retrieved_pages(citations, target_doc_id=doc_id)

            row = {
                "id": qid,
                "question": question,
                "doc_id": doc_id,
                "gold_pages": json.dumps(gold_pages, ensure_ascii=False),
                "retrieved_pages": json.dumps(retrieved_pages, ensure_ascii=False),
                "topk": config["topk"],
                "use_rerank": config["use_rerank"],
                "use_judge": config["use_judge"],
                "sim_threshold": config["sim_threshold"],
                "answer": answer,
                "n_citations": len(citations),
                "strict_r1": hit_at_k(citations, doc_id, gold_pages, 1),
                "strict_r3": hit_at_k(citations, doc_id, gold_pages, 3),
                "strict_r5": hit_at_k(citations, doc_id, gold_pages, 5),
                **conf_fields,
                **timing_fields,
            }

            rows.append(row)
            print(f"DEBUG appended row for qid={qid}, current rows={len(rows)}")

        except Exception as e:
            fail_count += 1
            print(f"ERROR on qid={qid}: {e}")
            import traceback
            traceback.print_exc()
            continue

    print(f"\nDEBUG total questions={len(questions)}, success={len(rows)}, fail={fail_count}")

    if not rows:
        raise RuntimeError("所有题目都评测失败，未生成任何结果，请根据上面的报错逐题排查。")

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_CSV, index=False, encoding="utf-8-sig")

    summary = summarize_results(df)

    with open(SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": config,
                "summary": summary,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    summary_md = build_summary_markdown(summary, config)
    with open(SUMMARY_MD, "w", encoding="utf-8") as f:
        f.write(summary_md)

    print("\n=== Done ===")
    print(f"逐题结果: {RESULTS_CSV}")
    print(f"汇总 JSON: {SUMMARY_JSON}")
    print(f"汇总 Markdown: {SUMMARY_MD}")

if __name__ == "__main__":
    main()