import json
from pathlib import Path

# 参数（你可以改数字做实验）
CHUNK_SIZE = 500
OVERLAP = 100

RAW_DIR = Path("data/raw_docs")
OUT_DIR = Path("data/chunks")
OUT_DIR.mkdir(parents=True, exist_ok=True)

files = list(RAW_DIR.glob("*.jsonl"))

print("处理文件：", [f.name for f in files])

for file_path in files:
    out_path = OUT_DIR / file_path.name

    with open(file_path, "r", encoding="utf-8") as f:
        pages = [json.loads(line) for line in f]

    with open(out_path, "w", encoding="utf-8") as out:
        for page in pages:
            text = page["text"]
            doc_id = page["doc_id"]
            page_num = page["page"]

            start = 0
            chunk_id = 0

            while start < len(text):
                end = start + CHUNK_SIZE
                chunk_text = text[start:end]

                chunk_data = {
                    "doc_id": doc_id,
                    "page": page_num,
                    "chunk_id": chunk_id,
                    "span": [start, end],
                    "text": chunk_text
                }

                out.write(json.dumps(chunk_data, ensure_ascii=False) + "\n")

                start += CHUNK_SIZE - OVERLAP
                chunk_id += 1

    print(f"{file_path.name} 切块完成")

print("全部完成")
