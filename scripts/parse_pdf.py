from pypdf import PdfReader
import json
from pathlib import Path

PDF_DIR = Path("data/pdfs")
OUT_DIR = Path("data/raw_docs")

OUT_DIR.mkdir(parents=True, exist_ok=True)

pdf_files = list(PDF_DIR.glob("*.pdf"))

print("发现 PDF 文件：", [p.name for p in pdf_files])

for pdf_path in pdf_files:
    reader = PdfReader(str(pdf_path))
    doc_id = pdf_path.stem
    out_path = OUT_DIR / f"{doc_id}.jsonl"

    written = 0

    with open(out_path, "w", encoding="utf-8") as f:
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text = text.replace("\n", " ").strip()
            if not text:
                continue

            data = {
                "doc_id": doc_id,
                "page": i + 1,
                "text": text
            }

            f.write(json.dumps(data, ensure_ascii=False) + "\n")
            written += 1

    print(f"{doc_id}: 总页数 {len(reader.pages)} → 写入 {written} 页")

print("全部完成！")
