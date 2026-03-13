import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("reports/emb_compare.csv")

ks = [1,3,5]
x = list(range(len(ks)))

plt.figure()
for _, row in df.iterrows():
    model = row["model"]
    strict = [row[f"strict_r@{k}"] for k in ks]
    soft = [row[f"soft_r@{k}"] for k in ks]
    plt.plot(x, strict, marker="o", label=f"{model} Strict")
    plt.plot(x, soft, marker="o", linestyle="--", label=f"{model} Soft")

plt.xticks(x, [str(k) for k in ks])
plt.xlabel("k")
plt.ylabel("Recall@k")
plt.title("Embedding Ablation (Strict vs Soft)")
plt.legend()
plt.tight_layout()
plt.savefig("reports/emb_compare.png", dpi=200)
print("Saved: reports/emb_compare.png")