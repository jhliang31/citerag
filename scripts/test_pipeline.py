from src.pipeline import run_query

answer, citations, confidence, timings = run_query(
    doc_id="os_tutorial",
    question="测试问题",
    topk=3
)

print("ANSWER:", answer[:200])
print("CITATIONS:", citations[0])
print("CONFIDENCE:", confidence)
print("TIMINGS:", timings)