# Day12 引用格式升级（CiteRAG）

## 目标
- 回答输出带引用，且引用可解释、可核对
- 引用列表包含 doc/page/chunk、chunk 摘要、相似度分数
- 提供本地 PDF 跳页链接，方便回到原文验证

## 输出结构

### 1) 回答正文
- 模型按要点输出
- 每条要点末尾给出引用条目（doc_id / 页码 / chunk_id）

示例：
- 引用: [1] os_tutorial p314 chunk0

### 2) 引用列表（可核对/可跳页）
每条引用包含：
- `doc_id`：文档标识
- `page`：PDF 页码（与解析记录一致）
- `chunk_id`：chunk 序号
- `faiss_score`：向量检索相似度（IndexFlatIP + normalize）
- `snippet`：chunk 摘要（默认取前 80 字）
- `open_link`：本地 PDF 跳页链接（推荐用 Edge 打开）

示例：
[1] os_tutorial p314 chunk0 (faiss=0.8077)  
摘要：...  
打开：file:///E:/Code/citerag/data/pdfs/os_tutorial.pdf#page=314  

## doc_id → PDF 路径映射
通过 `docs/doc_registry.json` 维护映射：

```json
{
  "os_tutorial": "E:/Code/citerag/data/pdfs/os_tutorial.pdf",
  "co": "E:/Code/citerag/data/pdfs/co.pdf"
}