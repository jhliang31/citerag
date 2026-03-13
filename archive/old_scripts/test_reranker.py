from sentence_transformers import CrossEncoder

model_name = "BAAI/bge-reranker-base"
reranker = CrossEncoder(model_name, device="cuda")

q = "什么是进程调度？"
chunks = [
    "进程调度是操作系统在多个就绪进程中选择一个运行的机制。",
    "TCP 是面向连接的传输层协议。",
    "Cache 是一种高速存储器。"
]

pairs = [(q, c) for c in chunks]
scores = reranker.predict(pairs)

print("Scores:")
for c, s in sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True):
    print(f"{s:.4f}\t{c}")