import json
from pathlib import Path
import re

chunks_dir = Path("data/chunks")
train_path = Path("data/sft_train_qa.jsonl")
train_path.parent.mkdir(exist_ok=True, parents=True)

train_data = []

# 遍历所有 jsonl chunk 文件
for chunk_file in chunks_dir.glob("*.jsonl"):
    with chunk_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

            text = chunk.get("text", "").strip()

            # 用正则拆分每个小题
            # 假设小题格式：4.xx 或 4.xx ...
            pattern = re.compile(r"(4\.\d+\s+.*?)(?=(4\.\d+)|$)", re.S)
            matches = pattern.findall(text)
            for match in matches:
                question_text = match[0].strip()
                if not question_text:
                    continue

                # 生成训练样本
                train_data.append({
                    "instruction": f"请回答以下问题：{question_text[:50]}...",
                    "input": "",
                    "output": question_text
                })

# 打印样本数和前 3 条样本
print(f"生成训练样本总数: {len(train_data)}")
for sample in train_data[:3]:
    print(sample)

# 保存 JSONL
with train_path.open("w", encoding="utf-8") as f:
    for item in train_data:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"优化后的训练集已保存至 {train_path}")