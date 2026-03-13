import pandas as pd
import matplotlib.pyplot as plt

KS = [1, 3, 5]

def compute_recalls(csv_path: str):
    df = pd.read_csv(csv_path)
    out = {}
    for k in KS:
        out[f"strict@{k}"] = df[f"hit_strict@{k}"].mean()
        out[f"soft@{k}"] = df[f"hit_soft@{k}"].mean()
    return out

files = [
    ("MiniLM (Day10)", "reports/retrieval_miniLM.csv"),
    ("BGE-small (Day10)", "reports/retrieval_bge_small.csv"),  # 如果你有 Day10 的 bge-small 也可放
    ("BGE no-rerank (Day11)", "reports/retrieval_bge_small_norerank.csv"),
    ("BGE + rerank (Day11)", "reports/retrieval_bge_small_rerank.csv"),
]

# 过滤掉不存在的文件（比如你没保留 Day10 的 bge_small.csv 也没关系）
existing = []
for name, path in files:
    try:
        open(path, "rb").close()
        existing.append((name, path))
    except FileNotFoundError:
        pass

stages = [x[0] for x in existing]
results = [compute_recalls(x[1]) for x in existing]

# 画“链条图”：只画最有解释力的 4 条线（Strict/Soft 的 k=1 和 k=3）
x = list(range(len(stages)))

plt.figure()
plt.plot(x, [r["strict@1"] for r in results], marker="o", label="Strict@1")
plt.plot(x, [r["soft@1"] for r in results], marker="o", linestyle="--", label="Soft@1")
plt.plot(x, [r["strict@3"] for r in results], marker="o", label="Strict@3")
plt.plot(x, [r["soft@3"] for r in results], marker="o", linestyle="--", label="Soft@3")

plt.xticks(x, stages, rotation=20, ha="right")
plt.ylim(0, 1.0)
plt.ylabel("Recall")
plt.title("Day10→Day11: Embedding & Reranker Improvement Chain")
plt.legend()
plt.tight_layout()
plt.savefig("reports/day10_day11_chain.png", dpi=200)
print("Saved: reports/day10_day11_chain.png")