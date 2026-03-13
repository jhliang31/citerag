import json
import os
import gc
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import PeftModel

os.environ["HF_HUB_OFFLINE"] = "1"

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
questions_path = os.path.join(project_root, "eval", "sft_test_questions.json")
adapter_path = os.path.join(
    project_root,
    "outputs",
    "qlora",
    "citerag_qwen25_lora_fresh_v3"
)
save_path = os.path.join(project_root, "reports", "citerag_qwen25_lora_clean100_v1.json")

base_model_name = "Qwen/Qwen2.5-3B-Instruct"

with open(questions_path, "r", encoding="utf-8") as f:
    questions = json.load(f)

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True
)

print("加载 tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(
    base_model_name,
    trust_remote_code=True,
    local_files_only=True
)

if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token


def build_prompt(question: str) -> str:
    return f"""你是一名计算机专业助教，请简洁回答问题。

问题：{question}
回答："""


def clean_generated_text(text: str) -> str:
    text = text.strip()

    if "回答：" in text:
        text = text.split("回答：", 1)[-1].strip()
    elif "答案：" in text:
        text = text.split("答案：", 1)[-1].strip()

    stop_markers = [
        "HumanLaTeX",
        "Humanine",
        "Humannaire",
        "HumanOLR",
        "HumanOLC",
        "Human法医",
        "Human法拉第",
        "Assistant:",
        "用户：",
        "问题：",
        "###",
        "\\documentclass",
        "In a virtual memory system",
        "In operating systems",
        "The main difference between",
        "FIFO (First-In-First-Out)",
        "野蛮人：",
        "助教：",
        "请简要回答",
        "请回答并解释"
    ]

    cut_pos = len(text)
    for marker in stop_markers:
        idx = text.find(marker)
        if idx != -1:
            cut_pos = min(cut_pos, idx)

    text = text[:cut_pos].strip()

    bad_endings = ["Human", "Assistant", "LaTeX"]
    for ending in bad_endings:
        if text.endswith(ending):
            text = text[:-len(ending)].strip()

    return text


def generate_answer(model, question: str) -> str:
    prompt = build_prompt(question)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=384,
            do_sample=False,
            repetition_penalty=1.05,
            no_repeat_ngram_size=4,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id
        )

    text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    text = clean_generated_text(text)
    return text


def load_base_model():
    print("加载纯 base model...")
    model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        local_files_only=True
    )
    model.eval()
    return model


def load_lora_model():
    print("当前 LoRA 路径:", adapter_path)
    print("加载 base model 并挂载 LoRA...")
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        local_files_only=True
    )
    model = PeftModel.from_pretrained(base_model, adapter_path)
    model.eval()
    return model


results = [{"question": q, "base": "", "lora": ""} for q in questions]

# 先跑 Base
base_model = load_base_model()

for i, q in enumerate(questions):
    print(f"\n[BASE] 问题 {i+1}/{len(questions)}: {q}")
    ans = generate_answer(base_model, q)
    print("BASE:", ans[:120])
    results[i]["base"] = ans

del base_model
gc.collect()
torch.cuda.empty_cache()

# 再跑 LoRA
lora_model = load_lora_model()

for i, q in enumerate(questions):
    print(f"\n[LORA] 问题 {i+1}/{len(questions)}: {q}")
    ans = generate_answer(lora_model, q)
    print("LORA:", ans[:120])
    results[i]["lora"] = ans

del lora_model
gc.collect()
torch.cuda.empty_cache()

with open(save_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\n对比结果已保存到: {save_path}")