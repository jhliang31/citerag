### Day 01 - 云服务器初始化

ECS 基本概念
实例（Instance）——「一台正在租的云电脑」
镜像（Image）——「这台云电脑的出厂系统」
安全组（Security Group）——「云服务器的门禁 + 防火墙」
公网 IP ——「这台云电脑的互联网地址」

## 实例信息
- 实例类型：gn6i（T4 16GB）
- CPU / 内存：8 vCPU / 31GiB
- GPU：NVIDIA T4 16GB
- 系统：Ubuntu 22.04（预装 GPU 驱动镜像）
- 系统盘：100GB

## 登录方式
- 用户名：ubuntu
- 登录方式：SSH Key   
- 连接工具：VS Code Remote-SSH / ssh      按CTRL+SHIFT+p，

## 网络与安全组
- 公网 IP：会随实例重启变化
- 安全组：仅开放 TCP 22 端口
- 说明：其他服务通过 SSH 隧道访问

## 基础环境确认
- 家目录：/home/ubuntu
- 系统盘挂载：/
- 基本命令：ls / pwd / df -h / free -h

## 今日记录
- 踩坑：实例重启后公网 IP 变化，导致 SSH 连接超时
- 解决：更新 SSH config 中的 HostName
- 备注：以后每次启动实例先检查公网 IP；维持云硬盘每小时固定会扣0.21元
