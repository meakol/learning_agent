<!-- prompt-version: 1 -->
## 1. 核心概念 / Core Concepts [p.1]
- [核心] 自注意力让每个位置直接与序列中所有位置交互，计算可并行。 [p.1]
  - EN: Self-attention links every position directly; computation is parallel. [p.1]
- [重点] 缩放因子 1/√d_k 防止点积过大导致 softmax 饱和。 [p.2]
  - EN: The 1/√d_k scale keeps softmax gradients stable. [p.2]
