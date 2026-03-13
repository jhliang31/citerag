import os
import torch
from datasets import load_dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TrainingArguments,
    BitsAndBytesConfig,
    Trainer,
    DataCollatorForSeq2Seq
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training


# =========================
# 路径设置
# =========================
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
train_file = os.path.join(project_root, "data", "train_sft_clean100.jsonl")

# 新目录，和前面实验彻底区分
output_dir = os.path.join(
    project_root,
    "outputs",
    "qlora",
    "citerag_qwen25_lora_clean100_v1"
)

model_name = "Qwen/Qwen2.5-3B-Instruct"

print(f"训练文件: {train_file}")
print(f"输出目录: {output_dir}")
print(f"基础模型: {model_name}")

os.makedirs(output_dir, exist_ok=True)


# =========================
# 读取数据
# =========================
dataset = load_dataset("json", data_files=train_file)["train"]
print(f"训练样本数: {len(dataset)}")


# =========================
# tokenizer
# =========================
tokenizer = AutoTokenizer.from_pretrained(
    model_name,
    trust_remote_code=True,
    local_files_only=True
)

if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

tokenizer.padding_side = "right"


# =========================
# 4bit量化配置
# =========================
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True
)


# =========================
# 加载基础模型
# =========================
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    quantization_config=bnb_config,
    device_map="auto",
    trust_remote_code=True,
    local_files_only=True
)

model.config.use_cache = False
model = prepare_model_for_kbit_training(model)


# =========================
# LoRA配置
# =========================
peft_config = LoraConfig(
    r=8,
    lora_alpha=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

model = get_peft_model(model, peft_config)
model.print_trainable_parameters()
model.gradient_checkpointing_enable()


# =========================
# 训练长度
# =========================
max_length = 384


# =========================
# response-only loss
# 统一使用“回答：”格式
# =========================
ANSWER_MARKERS = ["\n回答：", "回答：", "\n回答:", "回答:"]


def find_answer_start(text: str):
    positions = []
    for marker in ANSWER_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            positions.append((idx, marker))
    if not positions:
        return None, None

    idx, marker = min(positions, key=lambda x: x[0])
    return idx, marker


def tokenize_function(example):
    text = example["text"].strip()

    answer_idx, answer_marker = find_answer_start(text)
    if answer_idx is None:
        raise ValueError(f"样本中未找到回答标记: {text[:120]}")

    prefix_text = text[:answer_idx]
    answer_text = text[answer_idx:]  # 保留“回答：”本身参与训练

    # 关键：统一都不加 special tokens，避免监督错位
    prefix_ids = tokenizer(
        prefix_text,
        truncation=False,
        add_special_tokens=False
    )["input_ids"]

    answer_ids = tokenizer(
        answer_text,
        truncation=False,
        add_special_tokens=False
    )["input_ids"]

    input_ids = prefix_ids + answer_ids
    attention_mask = [1] * len(input_ids)
    labels = [-100] * len(prefix_ids) + answer_ids.copy()

    # 截断到 max_length
    input_ids = input_ids[:max_length]
    attention_mask = attention_mask[:max_length]
    labels = labels[:max_length]

    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "labels": labels
    }


# 先抽样检查几条，确认回答标记能正确找到
print("\n开始检查样本格式...")
for i in range(min(3, len(dataset))):
    sample = dataset[i]["text"]
    answer_idx, answer_marker = find_answer_start(sample)
    print("=" * 80)
    print(sample[:300])
    print("answer_idx:", answer_idx, "answer_marker:", answer_marker)


tokenized_dataset = dataset.map(
    tokenize_function,
    batched=False,
    remove_columns=dataset.column_names
)


# =========================
# 动态padding
# label部分自动pad为-100
# =========================
data_collator = DataCollatorForSeq2Seq(
    tokenizer=tokenizer,
    model=model,
    padding=True,
    label_pad_token_id=-100,
    pad_to_multiple_of=8
)


# =========================
# 训练参数
# =========================
training_args = TrainingArguments(
    output_dir=output_dir,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    num_train_epochs=2,
    learning_rate=2e-5,
    warmup_ratio=0.03,
    lr_scheduler_type="cosine",
    logging_steps=10,
    save_steps=100,
    save_total_limit=2,
    fp16=True,
    bf16=False,
    optim="paged_adamw_8bit",
    report_to="none",
    remove_unused_columns=False,
    gradient_checkpointing=True,
    max_grad_norm=0.3,
    dataloader_pin_memory=False
)


trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_dataset,
    data_collator=data_collator
)


# =========================
# 开始训练
# =========================
trainer.train()


# =========================
# 保存
# =========================
model.save_pretrained(output_dir)
tokenizer.save_pretrained(output_dir)

print(f"训练完成，模型已保存到: {output_dir}")