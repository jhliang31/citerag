import json
from pathlib import Path
import random

# 路径
chunks_dir = Path("data/chunks")  # jsonl 文件所在目录
train_path = Path("data/sft_train.jsonl")
train_path.parent.mkdir(exist_ok=True, parents=True)

all_chunks = []

# 遍历 jsonl 文件
for chunk_file in chunks_dir.glob("*.jsonl"):
    with chunk_file.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
                all_chunks.append(chunk)
            except json.JSONDecodeError as e:
                print(f"无法解析 {chunk_file} 第 {line_num} 行: {e}")

print(f"总 chunk 数: {len(all_chunks)}")

# 随机打乱
random.shuffle(all_chunks)

# 限制 chunk 数量，避免显存压力
sample_chunks = all_chunks[:250]  # 250 chunk -> 500 样本

train_data = []

for chunk in sample_chunks:
    text = chunk.get("text", "").strip()
    snippet = text[:200]

    # 样本1：直接回答
    instruction1 = f"请根据以下文档片段回答问题：{snippet[:50]}..."
    train_data.append({
        "instruction": instruction1,
        "input": text,
        "output": text
    })

    # 样本2：总结
    instruction2 = f"请总结文档片段的核心内容：{snippet[:50]}..."
    train_data.append({
        "instruction": instruction2,
        "input": text,
        "output": text
    })

# 保存 JSONL
with train_path.open("w", encoding="utf-8") as f:
    for item in train_data:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"训练数据生成完成，共 {len(train_data)} 条，保存至 {train_path}")

# 打印前 2 条样本检查
print("\n前 2 条训练样本：")
for item in train_data[:2]:
    print(item)