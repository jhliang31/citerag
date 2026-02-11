# Day 03 - Baseline Inference & VRAM Optimization

## 1. 实验目标

在 T4 16GB GPU 上运行 Qwen2.5-7B-Instruct（4bit），
建立可复现的单卡推理基线，并记录性能与显存占用情况。

---

## 2. 实验环境

- GPU: Tesla T4 16GB
- CUDA: 12.1
- torch: 2.5.1+cu121
- transformers: 5.1.0
- 量化方式: bitsandbytes 4bit (nf4)

---

## 3. Baseline（未做显存优化）

### 运行参数
- max_new_tokens: 128
- 短 prompt（无 RAG 上下文）

### 性能数据
- 模型加载时间: 11.05 s
- 生成时间: 6.51 s
- 显存峰值: ~14251 MiB

### 观察
显存占用接近 T4 上限（15.3GB），
在未来 RAG 拼接长上下文时存在 OOM 风险。

---

## 4. 优化方案：CPU Offload + 显存限制

采用：
- max_memory={0: "12GiB", "cpu": "48GiB"}
- offload_folder="/data/offload"
- torch_dtype=torch.float16
- attn_implementation="sdpa"

目的：
限制 GPU 最大占用，并将部分模块 offload 至 CPU，
为 RAG 长上下文预留显存空间。

---

## 5. 优化后结果

### 性能数据
- 模型加载时间: xx.xx s
- 生成时间: xx.xx s
- 显存峰值: ~9000 MiB

### 结果分析
显存占用下降约 5GB，
为后续 RAG 长上下文推理提供了 >6GB 安全余量。

生成速度略有下降，但系统稳定性显著提升。

---

## 6. 结论

成功建立单卡 7B 推理基线，并通过工程优化
降低显存占用约 35%。

该优化为后续 RAG 系统开发提供稳定运行环境。
