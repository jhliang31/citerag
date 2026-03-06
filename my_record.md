citerag/
├── assets/          # 图片、架构图、PPT素材
├── data/            # 原始PDF、chunk json
├── docs/            # 引用说明、格式文档
├── eval/            # 评测脚本/问题集
├── index/           # faiss.index + meta
├── logs/            # demo日志、confidence示例
├── reports/         # 实验结果、对比报告
├── scripts/         # 单次实验脚本
├── src/             # 核心pipeline逻辑
│   └── pipeline.py
├── app.py           # Gradio入口
└── .gitignore