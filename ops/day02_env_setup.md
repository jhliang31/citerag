# Day 02 - GPU 自检与 Python 环境搭建

## 环境信息
- OS：Ubuntu 22.04
- Python：3.10.12
- GPU：NVIDIA T4 16GB
- Driver：570.158.01
CUDA: 12.1
PyTorch: 2.5.1+cu121

## GPU 自检
- 使用 nvidia-smi 验证 GPU 正常
- 显存 16GB，无占用进程

## Python 环境
- 使用 venv 创建虚拟环境 rag-env
- 成功安装 PyTorch（GPU 版）及 RAG 相关依赖

## GPU 验证脚本
- 编写 scripts/env_check.py
- PyTorch CUDA available=True
- GPU 计算（矩阵乘法）成功

## 总结
- GPU、CUDA、PyTorch 环境验证完成
- 可用于后续模型推理与实验
