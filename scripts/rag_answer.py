import json
import numpy as np
import faiss
import torch
import os
from urllib.parse import quote
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from transformers import logging
logging.set_verbosity_error()

# ===== 配置 =====
EMB_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
LLM_MODEL = "Qwen/Qwen2.5-3B-Instruct"   # 先用3B更稳
INDEX_PATH = "index/faiss.index"
META_PATH = "index/meta.json"
TOPK = 3
DOC_REGISTRY_PATH = "docs/doc_registry.json"
PDF_PAGE_OFFSET = 0  # Edge里#page通常从1开始；如果总是偏一页改成0

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ===== 全局缓存（避免 Gradio 每次点击都重新加载模型）=====
_CACHE = {
    "emb_model": None,
    "index": None,
    "meta": None,
    "registry": None,
    "tokenizer": None,
    "llm": None,
}

def load_resources():
    """
    只加载一次：embedding / faiss / meta / registry / tokenizer / llm
    返回一个 dict，供后续函数使用
    """
    global _CACHE

    if _CACHE["emb_model"] is None:
        print("Loading embedding model...")
        _CACHE["emb_model"] = SentenceTransformer(EMB_MODEL, device=DEVICE)

    if _CACHE["index"] is None:
        print("Loading FAISS index...")
        _CACHE["index"] = faiss.read_index(INDEX_PATH)

    if _CACHE["meta"] is None:
        print("Loading meta...")
        _CACHE["meta"] = json.load(open(META_PATH, "r", encoding="utf-8"))

    if _CACHE["registry"] is None:
        _CACHE["registry"] = load_registry()

    if _CACHE["tokenizer"] is None:
        print("Loading tokenizer...")
        _CACHE["tokenizer"] = AutoTokenizer.from_pretrained(LLM_MODEL, use_fast=True)

    if _CACHE["llm"] is None:
        print("Loading LLM in 4bit...")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
        )
        _CACHE["llm"] = AutoModelForCausalLM.from_pretrained(
            LLM_MODEL,
            quantization_config=bnb_config,
            device_map="auto",
            dtype=torch.float16,
        )
        _CACHE["llm"].eval()

    return _CACHE




def load_registry(path=DOC_REGISTRY_PATH):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def to_file_url(pdf_path: str, page_1based: int) -> str:
    # Windows路径转 file:/// URL + #page
    p = pdf_path.replace("\\", "/")
    p = quote(p, safe=":/")
    return f"file:///{p}#page={page_1based}"

def build_citations(hit_ids, meta, scores, registry):
    """
    返回 citations: List[dict]
    每条包含 doc/page/chunk/snippet/link/score
    """
    citations = []
    for rank, (idx, sc) in enumerate(zip(hit_ids, scores), start=1):
        item = meta[int(idx)]
        doc_id = item.get("doc_id")
        page = int(item.get("page"))
        chunk_id = item.get("chunk_id")
        text = item.get("text", "")

        snippet = text.strip().replace("\n", " ")
        snippet = snippet[:80] + ("..." if len(snippet) > 80 else "")

        pdf_path = registry.get(doc_id)
        link = "N/A"
        if pdf_path:
            link = to_file_url(pdf_path, page + PDF_PAGE_OFFSET)

        citations.append({
            "cite_id": rank,              # [1],[2],[3]
            "doc_id": doc_id,
            "page": page,
            "chunk_id": chunk_id,
            "snippet": snippet,
            "faiss_score": float(sc),
            "link": link,
        })
    return citations

def build_context_and_cites(hit_ids, meta, citations):
    """
    context块里用 [1]/[2]/[3] 作为引用编号，
    同时给 LLM 的可选引用列表也用同样编号，避免长字符串引用
    """
    blocks = []
    cite_keys = []
    for cite, idx in zip(citations, hit_ids):
        item = meta[int(idx)]
        key = f"[{cite['cite_id']}] {item['doc_id']} p{item['page']} chunk{item['chunk_id']}"
        cite_keys.append(key)
        blocks.append(f"【{key}】\n{item['text']}")
    return "\n\n".join(blocks), cite_keys


def generate_answer(model, tokenizer, user_prompt, max_new_tokens=256):
    messages = [
        {"role": "system", "content": "你是一个严格基于【资料】回答的助手。不得编造。"},
        {"role": "user", "content": user_prompt},
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,   # ✅ 最稳：不要采样
        )

    decoded = tokenizer.decode(out[0], skip_special_tokens=True)

    # 尽量截取 assistant 之后（不同版本可能不含这个词，兜底返回末尾）
    if "assistant" in decoded:
        decoded = decoded.split("assistant")[-1].strip()
    return decoded.strip()


def main():
    print("Loading embedding model...")
    emb_model = SentenceTransformer(EMB_MODEL, device=DEVICE)

    print("Loading FAISS index...")
    index = faiss.read_index(INDEX_PATH)

    print("Loading meta...")
    meta = json.load(open(META_PATH, "r", encoding="utf-8"))

    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL, use_fast=True)

    print("Loading LLM in 4bit...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        LLM_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        dtype=torch.float16,     # ✅ 替代 torch_dtype（你那个warning就没了）
    )
    model.eval()

    print("System ready.\n")
    registry = load_registry()

    while True:
        q = input("Question (enter to quit): ").strip()
        if not q:
            break

        # ===== 检索 =====
        qvec = emb_model.encode([q], normalize_embeddings=True).astype(np.float32)
        scores, ids = index.search(qvec, TOPK)
        hit_ids = ids[0].tolist()
        hit_scores = scores[0].tolist()

        citations = build_citations(hit_ids, meta, hit_scores, registry)
        context, cite_keys = build_context_and_cites(hit_ids, meta, citations)

        # ===== 约束式 Prompt（抽取/少发挥）=====
        user_prompt = f"""请根据【资料】回答【问题】。

【资料】
{context}

【问题】
{q}

【要求】
1) 只能使用资料中的信息，不允许补充常识或推测。
2) 用不超过 4 条要点回答。
3) 每条要点末尾必须标注引用，引用只能从以下列表中选择：
{', '.join([f'({k})' for k in cite_keys])}
4) 如果资料不足，请不要扩展内容。
"""

        print("\nGenerating answer...\n")
        ans = generate_answer(model, tokenizer, user_prompt)

        print("====== 回答 ======\n")
        print(ans)

        print("\n====== 引用列表（可核对/可跳页） ======")
        for c in citations:
            print(f"[{c['cite_id']}] {c['doc_id']} p{c['page']} chunk{c['chunk_id']} (faiss={c['faiss_score']:.4f})")
            print(f"    摘要：{c['snippet']}")
            print(f"    打开：{c['link']}")
        print("\n====================\n")



if __name__ == "__main__":
    main()




#以下函数用于app.py的调用
def retrieve_topk(doc_id: str, question: str, topn: int = 5):
    """
    返回 candidates: List[dict]
    dict 至少包含 doc_id/page/chunk_id/text/faiss_score/jump_link
    注意：你这里的索引当前是全库索引，不按 doc_id 过滤（先保持一致）
    """
    R = load_resources()
    emb_model = R["emb_model"]
    index = R["index"]
    meta = R["meta"]
    registry = R["registry"]

    qvec = emb_model.encode([question], normalize_embeddings=True).astype(np.float32)
    scores, ids = index.search(qvec, topn)
    hit_ids = ids[0].tolist()
    hit_scores = scores[0].tolist()

    citations = build_citations(hit_ids, meta, hit_scores, registry)

    # 补齐 text 字段（你的 citations 里 snippet 只有前80字，pipeline 需要 full text）
    candidates = []
    for idx, sc, cite in zip(hit_ids, hit_scores, citations):
        item = meta[int(idx)]
        candidates.append({
            "doc_id": item.get("doc_id"),
            "page": int(item.get("page")),
            "chunk_id": item.get("chunk_id"),
            "text": item.get("text", ""),
            "faiss_score": float(sc),
            "jump_link": cite.get("link"),   # 统一叫 jump_link，后面 UI 更好对齐
        })
    return candidates

def generate_with_chunks(question: str, chunks, max_new_tokens: int = 256) -> str:
    """
    chunks: List[dict] (doc_id/page/chunk_id/text/...)
    """
    R = load_resources()
    model = R["llm"]
    tokenizer = R["tokenizer"]

    # 复用你已有的 build_context_and_cites，但它现在需要 hit_ids + meta
    # 我们这里直接拼一个“同风格”的 context（用 [1][2] 编号）
    blocks = []
    cite_keys = []
    for i, ch in enumerate(chunks, start=1):
        key = f"[{i}] {ch['doc_id']} p{ch['page']} chunk{ch['chunk_id']}"
        cite_keys.append(key)
        blocks.append(f"【{key}】\n{ch.get('text','')}")
    context = "\n\n".join(blocks)

    user_prompt = f"""请根据【资料】回答【问题】。

【资料】
{context}

【问题】
{question}

【要求】
1) 只能使用资料中的信息，不允许补充常识或推测。
2) 用不超过 4 条要点回答。
3) 每条要点末尾必须标注引用，引用只能从以下列表中选择：
{', '.join([f'({k})' for k in cite_keys])}
4) 如果资料不足，请不要扩展内容。
"""
    return generate_answer(model, tokenizer, user_prompt, max_new_tokens=max_new_tokens)

def rag_answer_once(doc_id: str, question: str, topk: int = 3):
    """
    返回 answer, citations(list)
    citations 是适合 UI 展示的结构（含 link）
    """
    R = load_resources()
    meta = R["meta"]
    registry = R["registry"]

    # 检索
    candidates = retrieve_topk(doc_id, question, topn=topk)

    # 生成
    ans = generate_with_chunks(question, candidates)

    # 做 UI 友好的 citations（带 snippet/link/score）
    citations = []
    for i, ch in enumerate(candidates, start=1):
        snippet = ch["text"].strip().replace("\n", " ")
        snippet = snippet[:80] + ("..." if len(snippet) > 80 else "")
        citations.append({
            "cite_id": i,
            "doc_id": ch["doc_id"],
            "page": ch["page"],
            "chunk_id": ch["chunk_id"],
            "snippet": snippet,
            "faiss_score": ch["faiss_score"],
            "link": ch.get("jump_link", "N/A"),
        })
    return ans, citations