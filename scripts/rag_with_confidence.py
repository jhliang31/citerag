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

# ===== 自动定位项目根目录 =====
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ===== 配置 =====
EMB_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
LLM_MODEL = "Qwen/Qwen2.5-3B-Instruct"   # 先用3B更稳
TOPK = 3
DOC_REGISTRY_PATH = os.path.join(PROJECT_ROOT, "docs", "doc_registry.json")
PDF_PAGE_OFFSET = 0  # Edge里#page通常从1开始；如果总是偏一页改成0
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ===== 使用 bge-small 索引=====
INDEX_DIR = os.path.join(PROJECT_ROOT, "index", "bge_small_zh_v15")
INDEX_PATH = os.path.join(INDEX_DIR, "faiss.index")
META_PATH = os.path.join(INDEX_DIR, "meta.json")

EMB_MODEL = "BAAI/bge-small-zh-v1.5"

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
你必须逐条核对回答中的每个要点是否被【资料】支持，并输出证据覆盖说明。

1) 必须先从【回答】中提取要点列表（按 claim_id=1,2,3...）。
2) 对每个要点，判断它是否能在【资料】中找到明确依据。
3) 即使整体判断为不支持，也必须逐条输出 coverage_map。
4) coverage_map 不允许为空。
5) 对于不支持的要点，citations 必须是空列表 []。
6) supported 取值只能是 "YES" 或 "NO"
   - 若 coverage >= 80，则 supported="YES"
   - 若 coverage < 80，则 supported="NO"
7) coverage 为 0-100 整数：=（被支持要点数 / 总要点数）*100 四舍五入
8) unsupported_points：列出 citations 为空的要点原文
9) reason：1-3 句话解释为什么支持/不支持（必须结合资料）
10) confidence_level：
   - HIGH：coverage >= 85
   - MEDIUM：coverage 在 50–84
   - LOW：coverage < 50

【输出格式】
必须输出严格 JSON，且只允许包含以下字段（不允许增加其他字段）：
{{
  "supported": "YES/NO",
  "coverage": 0,
  "confidence_level": "HIGH/MEDIUM/LOW",
  "coverage_map": [
   { {"claim_id": 1, "claim": "...", "citations": [1,2]}}
  ],
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
    meta_obj = json.load(open(META_PATH, "r", encoding="utf-8"))
    meta = meta_obj["chunks"]   # ✅ 关键：真正的 chunk 列表

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
2) 必须输出 1-4 条要点，每条一行，格式必须严格如下：
   [要点编号] 要点内容 (引用: [1][2]...)
3) 引用只能从以下编号中选择：
{', '.join([f'[{i+1}]' for i in range(len(cite_keys))])}
4) 如果资料不足，输出：
   [1] 资料不足，无法回答 (引用: [])
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



#以下用于app调用
import re

_EMB_CACHE = None

def get_embedder(device="cuda"):
    global _EMB_CACHE
    if _EMB_CACHE is None:
        from sentence_transformers import SentenceTransformer
        _EMB_CACHE = SentenceTransformer(EMB_MODEL, device=device)
    return _EMB_CACHE

def cosine_sim(a, b):
    import numpy as np
    a = a / (np.linalg.norm(a) + 1e-9)
    b = b / (np.linalg.norm(b) + 1e-9)
    return float(np.dot(a, b))

def extract_cite_ids_from_text(text: str):
    import re
    ids = re.findall(r"\[(\d+)\]", text)
    out = []
    for x in ids:
        i = int(x)
        if i not in out:
            out.append(i)
    return out

def _build_context_and_keys_from_chunks(chunks):
    blocks = []
    cite_keys = []
    for i, ch in enumerate(chunks, start=1):
        key = f"[{i}] {ch.get('doc_id')} p{ch.get('page')} chunk{ch.get('chunk_id')}"
        cite_keys.append(key)
        blocks.append(f"【{key}】\n{ch.get('text','')}")
    return "\n\n".join(blocks), cite_keys

def _safe_json_loads(s: str):
    # 1) 去掉 ```json ``` 包裹
    s2 = s.strip()
    s2 = re.sub(r"^```json\s*", "", s2)
    s2 = re.sub(r"^```\s*", "", s2)
    s2 = re.sub(r"\s*```$", "", s2)

    # 2) 直接尝试 parse
    try:
        return json.loads(s2)
    except Exception:
        pass

    # 3) 再从文本中抓最大 JSON 块
    m = re.search(r"\{[\s\S]*\}", s2)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    return {
        "supported": "NO",
        "coverage": 0,
        "confidence_level": "LOW",
        "coverage_map": [],
        "unsupported_points": ["Judge 输出无法解析为 JSON"],
        "reason": "LLM judge 输出不是严格 JSON，已降级处理。"
    }

def _extract_keywords_cn(text: str, max_k=8):
    kws = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    seen = set()
    out = []
    for k in kws:
        if k not in seen:
            seen.add(k)
            out.append(k)
        if len(out) >= max_k:
            break
    return out

def judge_with_confidence(question: str, answer: str, top_chunks, model, tokenizer, sim_threshold: float = 0.52):

    context, cite_keys = _build_context_and_keys_from_chunks(top_chunks)

    claims = extract_claims_llm(model, tokenizer, answer)
    if not claims:
        claims = [{"claim_id": 1, "claim": answer.strip()[:200]}]

    embedder = get_embedder(device=DEVICE)  # ✅ 放外面，且用全局 DEVICE

    coverage_map = []
    unsupported_points = []
    supported_cnt = 0
    

    for c in claims:
        cid = int(c["claim_id"])
        claim_text = str(c["claim"]).strip()

        cites = extract_cite_ids_from_text(claim_text)

        evidence = ""
        for cid2 in cites:
            if 1 <= cid2 <= len(top_chunks):
                evidence += (top_chunks[cid2 - 1].get("text", "") or "") + "\n"

        sim = None
        is_supported = False
        if cites and evidence.strip():
            v1 = embedder.encode([claim_text], normalize_embeddings=True)[0]
            v2 = embedder.encode([evidence], normalize_embeddings=True)[0]
            sim = cosine_sim(v1, v2)
            is_supported = sim >= sim_threshold  

        if is_supported:
            supported_cnt += 1
        else:
            unsupported_points.append(claim_text)
            cites = []

        coverage_map.append({
            "claim_id": cid,
            "claim": claim_text,
            "citations": cites,
            "sim": sim
        })

    total = len(coverage_map)
    coverage = int(round(100 * supported_cnt / total)) if total > 0 else 0

    supported = "YES" if coverage >= 80 else "NO"
    if coverage >= 85:
        level = "HIGH"
    elif coverage >= 50:
        level = "MEDIUM"
    else:
        level = "LOW"

    reason = f"共{total}条要点，支持{supported_cnt}条。"

    return {
        "supported": supported,
        "coverage": coverage,
        "confidence_level": level,
        "coverage_map": coverage_map,
        "unsupported_points": unsupported_points,
        "reason": reason
    }

#用于调整coverage只在0与100之间选择
import re
import json
import torch


def extract_claims_llm(model, tokenizer, answer: str, max_new_tokens=256):
    """
    不用 LLM 抽取，直接用“行首编号”切分要点，避免把引用里的 [1] 误当成要点编号。
    支持两种常见格式：
    1) 行首: [1] ...
    2) 行首: 1. ... / 1) ... / 1、...
    """
    import re

    ans = answer.strip()

    # 1) 行首 [1] 格式（必须是行首，避免匹配引用里的([1] ...)）
    pattern1 = re.findall(r"(?m)^\s*\[(\d+)\]\s*(.+?)(?=^\s*\[\d+\]|\Z)", ans, flags=re.S)
    if pattern1:
        return [{"claim_id": int(i), "claim": c.strip()} for i, c in pattern1]

    # 2) 行首 1. / 1) / 1、 格式（必须行首）
    pattern2 = re.findall(r"(?m)^\s*(\d+)[\.\)\、]\s*(.+?)(?=^\s*\d+[\.\)\、]|\Z)", ans, flags=re.S)
    if pattern2:
        return [{"claim_id": int(i), "claim": c.strip()} for i, c in pattern2]

    # 3) 兜底：整段当一个
    return [{"claim_id": 1, "claim": ans}]

def judge_one_claim_llm(model, tokenizer, question: str, claim: str, context: str, max_new_tokens=192):
    """
    对单条 claim 做判定，只输出 JSON：
    {"supported": true/false, "citations":[1,2], "reason":"..."}
    """
    prompt = f"""你是事实核查员，只依据【资料】判断【要点】是否被支持。
必须输出严格 JSON，不要输出其他文字。

【问题】
{question}

【资料】
{context}

【要点】
{claim}

【规则】
- 如果资料能直接支持该要点：supported=true，并给出 citations（引用编号列表，如 [1] 或 [1,2]）
- 如果不能直接支持：supported=false，citations=[]
- reason 用一句话说明原因（要结合资料）

【输出JSON】
{{"supported": true, "citations": [1], "reason": "..."}}"""
    messages = [
        {"role": "system", "content": "你是严谨核查员，只输出JSON。"},
        {"role": "user", "content": prompt},
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    decoded = tokenizer.decode(out[0], skip_special_tokens=True)
    # 提取 JSON 对象
    m = re.search(r"\{[\s\S]*\}", decoded)
    if not m:
        return {"supported": False, "citations": [], "reason": "judge未输出JSON"}
    try:
        obj = json.loads(m.group(0))
        sup = bool(obj.get("supported", False))
        cites = obj.get("citations", [])
        # 规范 citations 为 int 列表
        cites2 = []
        for c in cites:
            try:
                cites2.append(int(c))
            except:
                pass
        return {"supported": sup, "citations": cites2, "reason": str(obj.get("reason", ""))}
    except Exception:
        return {"supported": False, "citations": [], "reason": "judge JSON解析失败"}