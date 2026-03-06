# CiteRAG 项目研究问题设计

## 一、项目目标

CiteRAG 的目标是构建一个 **可解释、可验证的中文 PDF 知识库问答系统（RAG）**。

系统整体流程如下：

PDF → 文档解析 → 文本切块（Chunking） → 向量化（Embedding） → FAISS 向量检索 → （可选）Reranker 重排 → LLM 生成回答 → 可信度评估（LLM Judge）

系统输出需要满足以下要求：

- 回答中包含 **结构化引用信息**（doc_id / page / chunk_id）
- 支持 **原文跳转链接**（file:///xxx.pdf#page=N）
- 提供 **可信度评估结果**（supported / coverage / confidence_level 等）

为了系统性评估该 RAG 系统，本项目设计了一系列研究问题，并通过实验进行验证。

当前评测数据集为：

- **20 条人工构造 QA 问题**
- 每条问题包含 **标准答案所在文档与页码（gold_pages）**

评估指标包括：

- Strict Recall@k（检索阶段指标）
- Judge Coverage（回答被证据支持比例）
- Confidence Level（HIGH / MEDIUM / LOW）
- Latency（retrieve / rerank / generate / judge）

---

# RQ1：Chunk Size 对检索效果与回答可信度的影响

## 研究动机

在 RAG 系统中，文本切块（Chunking）是影响检索效果的重要因素。

如果 chunk 过小：

- 语义可能被过度切分
- 上下文信息不足

如果 chunk 过大：

- 检索粒度变粗
- 相关内容可能被噪声稀释

因此需要系统研究 **chunk size 对检索质量与回答可信度的影响**。

---

## 研究假设

- 较小的 chunk size 可能提升 **Strict Recall@k**，因为检索粒度更细。
- 较大的 chunk size 可能提升 **Judge Coverage**，因为提供了更完整上下文。
- 较小 chunk 可能增加 **索引规模与检索延迟**。

---

## 评估指标

- Strict Recall@1 / Recall@3 / Recall@5
- Judge Coverage（%）
- Confidence Level 分布
- 系统延迟（Latency）

---

## 实验设置

实验将构建三种不同的 chunk 配置：

| chunk_size | overlap |
|-------------|--------|
| 256 | 50 |
| 500 | 100（当前 baseline） |
| 800 | 100 |

实验流程：

1. 重新构建 chunk 数据
2. 重新生成 embedding 与 FAISS index
3. 在 QA 评测集上运行检索实验
4. 运行完整 RAG pipeline（含 Judge）
5. 记录 Recall@k、coverage、latency 等指标

---

# RQ2：Reranker 是否能稳定提升检索质量与回答可信度

## 研究动机

传统向量检索（bi-encoder）虽然效率高，但在 Top-K 结果中可能存在排序误差。

Cross-Encoder Reranker 可以对候选文档进行 **精细重排**，从而提高最相关结果的排名。

因此需要验证：

**Reranker 是否能够稳定提升检索质量与回答可信度。**

---

## 研究假设

引入 Reranker 后：

- Strict Recall@1 会显著提升
- Judge Coverage 可能提升（因为检索到更相关证据）

---

## 评估指标

- Strict Recall@1 / Recall@3 / Recall@5
- Judge Coverage（%）
- rerank_sec（重排耗时）

---

## 当前实验结果

使用 **BAAI/bge-reranker-base** 的实验结果：

| 指标 | 无 Reranker | 使用 Reranker |
|------|-------------|---------------|
| Strict Recall@1 | 0.20 | 0.40 |
| Strict Recall@5 | 0.75 | 0.85 |

实验结果表明：

Reranker 能显著提升 **Top-1 检索准确率**。

后续实验将进一步评估其对 **回答可信度（coverage）** 的影响。

---

## 实验设置

固定检索 TopK = 5

对比两种设置：


use_rerank = False
use_rerank = True


运行完整 pipeline 并统计评测指标。

---

# RQ3：可信度评估模块是否能有效识别回答的证据支持情况

## 研究动机

大语言模型在生成回答时可能产生 **幻觉（Hallucination）**。

即生成内容未被检索到的证据支持。

因此需要一个 **自动可信度评估模块（Confidence Judge）** 来检测：

- 回答中的要点是否被引用证据支持
- 整体回答可信程度

---

## 方法

本项目实现了一种基于 embedding 相似度的判断方法：

1. 从回答中抽取 **claim（要点）**
2. 从引用编号中定位对应 **evidence chunk**
3. 计算：


sim = cos_sim(embedding(claim), embedding(evidence))


4. 当


sim ≥ sim_threshold


时认为该要点被证据支持。

---

## 评估指标

- Coverage（支持的 claim 比例）
- Confidence Level（HIGH / MEDIUM / LOW）
- Unsupported claims 数量

---

## 阈值实验

实验将测试不同的相似度阈值：

| sim_threshold |
|--------------|
| 0.45 |
| 0.50 |
| 0.52 |
| 0.55 |
| 0.60 |

---

## 预期趋势

随着阈值提高：


coverage ↓
confidence_level ↓
判定更严格


该机制可以实现 **可信度严格程度的可调节控制**。

---

# RQ4：Embedding 模型选择对检索效果的影响

## 研究动机

Embedding 模型的质量直接影响向量检索效果。

不同模型在：

- 语言适配
- 表示能力
- 计算效率

方面存在差异。

---

## 实验模型

本项目对比了两个 embedding 模型：

- paraphrase-multilingual-MiniLM-L12-v2
- BAAI/bge-small-zh-v1.5

---

## 实验结果

| 指标 | MiniLM | bge-small-zh |
|------|--------|--------------|
| Strict Recall@1 | 0.10 | 0.20 |
| Strict Recall@3 | 0.40 | 0.60 |
| Strict Recall@5 | 0.40 | 0.75 |

---

## 结论

bge-small-zh-v1.5 在中文语料上明显优于 MiniLM。

因此当前系统使用：


BAAI/bge-small-zh-v1.5


作为默认 embedding 模型。

---

# 总结

本项目围绕以下四个核心研究问题展开：

1️⃣ Chunk Size 对检索效果的影响  
2️⃣ Reranker 对检索排序质量的提升  
3️⃣ 可信度评估机制对幻觉检测的有效性  
4️⃣ Embedding 模型选择的性能差异  

通过系统实验与消融分析，可以为 **构建可靠的 RAG 系统提供经验依据**。