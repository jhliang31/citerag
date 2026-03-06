from src.pipeline import run_query

answer, citations, confidence, timings = run_query(
    doc_id="os_tutorial",
    question="测试问题",
    topk=3,
    use_rerank=True,
    use_judge=True,
)

print("judge:", confidence)
print("timings:", timings)