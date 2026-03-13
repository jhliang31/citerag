import os
import json
import pandas as pd
import matplotlib.pyplot as plt

from eval.run_eval import main, SUMMARY_JSON, RESULTS_CSV, REPORTS_DIR, DEFAULT_TOPK, DEFAULT_USE_RERANK, DEFAULT_USE_JUDGE

SIM_THRESHOLDS = [0.65,0.70, 0.75, 0.80, 0.85, 0.90]

summary_list = []

for t in SIM_THRESHOLDS:
    print(f"\n=== Running eval with sim_threshold={t} ===")
    
    # 临时修改 run_eval.py 配置
    from eval.run_eval import DEFAULT_SIM_THRESHOLD
    DEFAULT_SIM_THRESHOLD = t

    # 调用 Day16 pipeline
    main()

    # 读取 summary.json
    with open(SUMMARY_JSON, "r", encoding="utf-8") as f:
        summary_json = json.load(f)
    summary_data = summary_json["summary"]

    # 构造表行
    summary_row = {
        "sim_threshold": t,
        "strict_r1": summary_data["strict_recall_at_1"],
        "strict_r3": summary_data["strict_recall_at_3"],
        "strict_r5": summary_data["strict_recall_at_5"],
        "avg_coverage": summary_data["avg_coverage"],
        "HIGH": summary_data["confidence_level_dist"].get("HIGH", 0),
        "MEDIUM": summary_data["confidence_level_dist"].get("MEDIUM", 0),
        "LOW": summary_data["confidence_level_dist"].get("LOW", 0),
        "avg_retrieve_sec": summary_data["avg_retrieve_sec"],
        "avg_rerank_sec": summary_data["avg_rerank_sec"],
        "avg_generate_sec": summary_data["avg_generate_sec"],
        "avg_judge_sec": summary_data["avg_judge_sec"],
    }

    summary_list.append(summary_row)

# 保存 CSV
df = pd.DataFrame(summary_list)
sweep_csv = REPORTS_DIR / "eval_threshold_sweep.csv"
df.to_csv(sweep_csv, index=False, encoding="utf-8-sig")
print(f"\nThreshold sweep results saved to {sweep_csv}")

# --------------------------
# 绘图
# --------------------------
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
fig_dir = REPORTS_DIR / "figures"
fig_dir.mkdir(exist_ok=True)

plt.figure(figsize=(6,4))
plt.plot(df['sim_threshold'], df['avg_coverage'], marker='o', label='Coverage')
plt.plot(df['sim_threshold'], df['strict_r1'], marker='x', label='Recall@1')
plt.plot(df['sim_threshold'], df['strict_r3'], marker='^', label='Recall@3')
plt.plot(df['sim_threshold'], df['strict_r5'], marker='s', label='Recall@5')
plt.xlabel("sim_threshold")
plt.ylabel("比例")
plt.title("Threshold Sweep: Coverage & Recall")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig(fig_dir / "threshold_sweep.png")
plt.show()

# Confidence Level 柱状图
plt.figure(figsize=(6,4))
plt.bar(df['sim_threshold']-0.02, df['HIGH'], width=0.02, label='HIGH')
plt.bar(df['sim_threshold'], df['MEDIUM'], width=0.02, label='MEDIUM')
plt.bar(df['sim_threshold']+0.02, df['LOW'], width=0.02, label='LOW')
plt.xlabel("sim_threshold")
plt.ylabel("数量")
plt.title("Threshold Sweep: Confidence Level Distribution")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.savefig(fig_dir / "threshold_confidence.png")
plt.show()