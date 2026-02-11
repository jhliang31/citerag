# Day 01 - 云服务器搭建与远程开发环境配置

## 1. 实验目标

搭建可用于大模型推理与RAG开发的云端GPU环境，
确保远程连接稳定、GPU可用、开发流程可复现。

---

## 2. 服务器配置

- 实例类型: T4 16GB
- 系统: Ubuntu 22.04
- GPU 驱动: 预装镜像
- 远程方式: SSH + VSCode Remote

---

## 3. 网络与安全组

- 开放端口: 22 (SSH)
- 出站流量: 默认允许
- HuggingFace 访问问题:
  - 发现 huggingface.co 无法访问
  - 通过网络排查确认 443 被限制
  - 解决方案: 使用 hf-mirror.com

---

## 4. 关键命令记录

```bash
ssh ubuntu@<IP>
nvidia-smi
