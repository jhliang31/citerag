import os
import json
import glob
import argparse
from datetime import datetime

import numpy as np
from tqdm import tqdm

import faiss
from sentence_transformers import SentenceTransformer


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks_glob", default="data/chunks/*.jsonl", help="Glob for chunk jsonl files")
    ap.add_argument("--model", required=True, help="SentenceTransformer model name")
    ap.add_argument("--out_dir", required=True, help="Output dir for faiss.index + meta.json")
    ap.add_argument("--batch_size", type=int, default=64)
    ap.add_argument("--device", default="cuda", help="cuda or cpu")
    ap.add_argument("--no_normalize", action="store_true", help="Disable embedding normalization (default on)")
    return ap.parse_args()


def load_chunks(chunks_glob: str):
    files = sorted(glob.glob(chunks_glob))
    if not files:
        raise FileNotFoundError(f"No chunk files found with glob: {chunks_glob}")

    all_chunks = []
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                if "text" not in obj or not str(obj["text"]).strip():
                    continue
                obj["_source_file"] = os.path.basename(fp)
                all_chunks.append(obj)

    return all_chunks, files


def main():
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    print("Loading chunks...")
    chunks, files = load_chunks(args.chunks_glob)
    print(f"Total chunks: {len(chunks)}")
    print(f"Chunks glob: {args.chunks_glob}")

    texts = [c["text"] for c in chunks]

    print(f"Loading embedding model: {args.model}")
    model = SentenceTransformer(args.model, device=args.device)

    normalize = not args.no_normalize
    print(f"Encoding... (batch_size={args.batch_size}, normalize={normalize}, device={args.device})")
    embeddings = model.encode(
        texts,
        batch_size=args.batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=normalize,
    ).astype(np.float32)

    dim = int(embeddings.shape[1])
    print(f"Embedding dim: {dim}")

    print("Building FAISS index (IndexFlatIP)...")
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss_path = os.path.join(args.out_dir, "faiss.index")
    meta_path = os.path.join(args.out_dir, "meta.json")

    faiss.write_index(index, faiss_path)

    meta = {
        "embed_model": args.model,
        "embed_dim": dim,
        "normalize": normalize,
        "index_type": "IndexFlatIP",
        "ntotal": int(index.ntotal),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "chunks_glob": args.chunks_glob,
        "source_files": [os.path.basename(p) for p in files],
        "chunks": chunks,  # 保持你原来的行为：把chunks都存进去
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    print("✅ Build finished!")
    print("Index size:", index.ntotal)
    print("Saved:", faiss_path)
    print("Saved:", meta_path)


if __name__ == "__main__":
    main()