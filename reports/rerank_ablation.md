## Reranker 消融实验（BGE-small + top10 重排）

固定：chunk_size=500，IndexFlatIP+normalize，评测集=20题，k=1/3/5  
变量：是否启用 reranker（BAAI/bge-reranker-base），重排候选数 topN=10

### Baseline（无 rerank）
Strict R@1=0.20，R@3=0.60，R@5=0.75  
Soft   R@1=0.30，R@3=0.75，R@5=0.80  

### + Rerank（top10）
Strict R@1=0.40，R@3=0.65，R@5=0.85  
Soft   R@1=0.45，R@3=0.70，R@5=0.90  

结论：reranker 显著提升 top1 精度（Strict R@1 翻倍），更适合用于生成阶段的证据选择。
