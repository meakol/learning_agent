<!-- prompt-version: 1 -->
## 1. Core idea [p.1]
- [Core] Self-attention: every token attends to all tokens; computation is parallel. [p.1]
- [Key] Cost: O(n²d); long sequences are the bottleneck. [p.9]

:::branches Parallel bottlenecks
- [Core] RNN: sequential; path length O(n)
- [Key] CNN: local receptive field
:::
