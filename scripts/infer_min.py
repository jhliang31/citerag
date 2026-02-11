import torch
import time
import gc
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

model_name = "Qwen/Qwen2.5-7B-Instruct"

start_total = time.time()

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(model_name)

print("Configuring 4bit quantization...")
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
)

print("Loading model...")
start_load = time.time()
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    quantization_config=bnb_config,
    device_map="auto",
    torch_dtype=torch.float16,
    attn_implementation="sdpa",
    max_memory={0: "12GiB", "cpu": "48GiB"},
    offload_folder="/data/offload",
)

model.eval()
end_load = time.time()
print(f"Model loaded in {end_load - start_load:.2f} seconds")

prompt = "请用三句话解释什么是向量检索。"
messages = [
    {"role": "system", "content": "你是一个严谨的AI助手。"},
    {"role": "user", "content": prompt}
]

text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

# ✅ 限制输入长度（省显存关键）
inputs = tokenizer(
    text,
    return_tensors="pt",
    truncation=True,
    max_length=2048
).to("cuda")

print("Generating...")
start_gen = time.time()

with torch.inference_mode():
    outputs = model.generate(
        **inputs,
        max_new_tokens=128,
        temperature=0.7
    )

end_gen = time.time()

generated_ids = outputs[0][inputs.input_ids.shape[-1]:]
response = tokenizer.decode(generated_ids, skip_special_tokens=True)

print("\n===== 模型输出 =====\n")
print(response.strip())

print(f"\nGeneration time: {end_gen - start_gen:.2f} seconds")
print(f"Total runtime: {time.time() - start_total:.2f} seconds")

# ✅ 清理缓存（多次实验更稳）
gc.collect()
torch.cuda.empty_cache()

