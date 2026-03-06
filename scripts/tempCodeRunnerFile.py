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

def judge_support(model, tokenizer, question, answer, context, cite_keys, max_new_tokens=256):
    """
    二次调用模型判断回答是否被资料支持，并给出覆盖度与问题点。
    输出要求为 JSON，便于后续写入日志/表格。
    """
    judge_prompt = f"""你是一个严格的事实核查员。请只依据【资料】判断【回答】是否被支持。

【问题】
{question}

【资料】
{context}

【回答】
{answer}

【引用可用列表】
{', '.join(cite_keys)}

【任务】
1) 判断【回答】是否被【资料】整体支持：supported 取值只能是 "YES" 或 "NO"
2) 给出证据覆盖度 coverage（0-100 的整数）：表示回答中有多少内容能在资料中找到依据
3) 列出 unsupported_points：指出哪些要点/句子无法被资料支持（如果 supported=YES 可以为空列表）
4) 给出 reason：用 1-3 句话说明判断依据（必须引用资料中的关键线索，不允许泛泛而谈）
5) 给出 confidence_level：只能是 "HIGH" / "MEDIUM" / "LOW"
   - HIGH：supported=YES 且 coverage>=80
   - MEDIUM：supported=YES 且 coverage在50-79，或 supported=NO 但只是少量细节缺失
   - LOW：supported=NO 且 coverage<50 或存在明显编造

【输出格式】
请输出严格 JSON（不要输出多余文本），字段如下：
{{
  "supported": "YES/NO",
  "coverage": 0,
  "confidence_level": "HIGH/MEDIUM/LOW",
  "unsupported_points": ["..."],
  "reason": "..."
}}
"""
    messages = [
        {"role": "system", "content": "你是严谨的核查员，只能根据资料判断。"},
        {"role": "user", "content": judge_prompt},
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False
        )

    decoded = tokenizer.decode(out[0], skip_special_tokens=True)
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

    os.makedirs("logs", exist_ok=True)
    log_path = os.path.join("logs", "day13_confidence_examples.md")

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
        print("\nGenerating confidence check...\n")
        judge_json = judge_support(model, tokenizer, q, ans, context, cite_keys)

        print("====== 可信度评分（LLM Judge） ======\n")
        print(judge_json)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"## Q: {q}\n\n")
            f.write("### Answer\n")
            f.write(ans + "\n\n")
            f.write("### Citations\n")
            for c in cite_keys:
                f.write(f"- {c}\n")
            f.write("\n### Judge\n")
            f.write("```json\n" + judge_json + "\n```\n\n")
            f.write("---\n\n")

        print("\n====================\n")
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