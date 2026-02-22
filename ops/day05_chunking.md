Day05：Chunking（文本切块）Baseline 实现
一、今日目标

实现 RAG 数据预处理中的第二步：

将页级文本切分为带 overlap 的固定长度文本块（chunk），为后续 embedding 和向量检索做准备。

二、背景说明

在 Day04 中，我已经完成：

PDF → 页级文本（jsonl）

但页级文本存在以下问题：

每页文本长度不一致

单页可能过长，直接 embedding 会引入噪声

页级边界不一定等于语义边界

因此需要进行更细粒度的切块（chunking）。

三、实现方案
1. 参数设计

本次采用固定长度切块方式：

CHUNK_SIZE = 500

OVERLAP = 100

即：

每个 chunk 长度为 500 字符
相邻 chunk 之间重叠 100 字符

2. 切块逻辑

对于每一页文本：

从 start = 0 开始

每次截取区间 [start, start + CHUNK_SIZE]

下一次 start 增加 (CHUNK_SIZE - OVERLAP)

这样可以保证：

文本不会遗漏

减少语义边界截断带来的信息损失

3. 每个 chunk 的存储字段

每个 chunk 保存为一行 JSON，包含：

doc_id：文档标识

page：来源页码

chunk_id：页内编号

span：原文本位置区间

text：chunk 内容

示例结构：

{
"doc_id": "co",
"page": 12,
"chunk_id": 3,
"span": [1200, 1700],
"text": "......"
}

四、生成结果

成功生成：

data/chunks/
co.jsonl
network.jsonl
os_tutorial.jsonl

数据处理流程更新为：

PDF
↓
page-level json
↓
chunk-level json

五、理论思考
1. 为什么不能直接用整页做 embedding？

页级文本长度不稳定

长文本 embedding 容易引入噪声

检索时可能匹配到无关内容

2. 为什么需要 overlap？

如果没有 overlap：

文本语义可能被截断，例如：

语义A的后半部分在 chunk1
语义A的前半部分在 chunk2

导致 embedding 表示不完整。

Overlap 的作用是：

缓解语义边界问题，提高召回的稳定性。

3. chunk size 会影响什么？

太小 → 语义碎片化

太大 → 噪声增加

合理的 chunk size 需要通过实验验证

后续将在 Week2 做消融实验对比不同 chunk size 的 Recall@k 表现。

六、阶段总结

本日完成：

多文档统一切块处理

支持可调参数（chunk_size / overlap）

输出结构化 chunk 数据

为后续 embedding 和向量索引阶段打下基础。

七、下一步计划

chunk → embedding → FAISS index

进入向量检索阶段。
