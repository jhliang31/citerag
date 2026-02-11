# Day 03 - Baseline Inference & VRAM Optimization

## 1. 实验目标

在单卡 Tesla T4 16GB GPU 上运行 Qwen2.5-7B-Instruct（4bit 量化），
建立可复现的大模型推理基线，并分析显存占用情况，
为后续 RAG 系统开发提供稳定运行环境。

---

## 2. 实验环境

- GPU: Tesla T4 (16GB)
- CUDA: 12.1
- PyTorch: 2.5.1+cu121
- Transformers: 5.1.0
- 量化方式: bitsandbytes 4bit (nf4)
- 推理模式: 单样本推理 (batch_size=1)

---

## 3. Baseline 测试（未进行显存优化）

### 运行参数

- max_new_tokens = 128
- 短 prompt（无 RAG 上下文）
- device_map = "auto"

### 性能数据

- 模型加载时间: 11.05 s
- 生成时间: 6.51 s
- 总运行时间: 20.59 s
- 显存峰值: ~14251 MiB

### 观察

在仅使用短 prompt 的情况下，
显存占用已达到 14.2GB（接近 T4 上限 15.3GB），
仅剩约 1GB 余量。

若后续 RAG 引入长上下文（多 chunk 拼接），
极易发生 OOM（Out Of Memory）错误。

---

## 4. 优化方案：CPU Offload + 显存限制

为提升系统稳定性，引入以下优化策略：

- max_memory = {0: "12GiB", "cpu": "48GiB"}
- offload_folder = "/data/offload"
- torch_dtype = torch.float16
- attn_implementation = "sdpa"

核心思路：

限制 GPU 最大显存占用，
将部分模块自动 offload 至 CPU，
为长上下文推理预留显存空间。

---

## 5. 优化后测试结果

### 性能数据

- 模型加载时间: ~12 s
- 生成时间: ~6 s
- 显存峰值: ~9000 MiB

### 对比分析

| 指标 | Baseline | 优化后 |
|------|----------|--------|
| 显存峰值 | ~14251 MiB | ~9000 MiB |
| 显存余量 | ~1GB | ~6GB+ |
| 生成速度 | 6.51 s | ~6 s |

显存占用下降约 35%~40%，
系统稳定性显著提升。

生成速度略有波动，但整体影响可接受。

---

## 6. 结论

成功在单卡 T4 上建立 7B 模型推理基线，
并通过工程优化显著降低显存峰值。

优化后系统具备足够显存余量，
可支持后续 RAG 长上下文推理实验。

本阶段完成：

- 单卡 7B 推理环境搭建
- 性能基线测量
- 显存瓶颈分析
- 工程级显存优化

为后续 RAG 实验阶段奠定稳定基础。
