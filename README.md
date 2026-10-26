# 课堂笔记智能体 · Lecture Notes Agent

上传 PPTX 或 PDF 课件，左侧保留原始版式预览，右侧由智能体流式生成学生笔记式的知识点总结：精简改写、中/英/双语、5 级详细度、按重要度着色、标注来源页码。

同一页面还提供学习计划、里程碑测试与基于课件的问答。

## 功能

**课件解析与预览**

- PPTX：提取文字、表格、图片、讲者备注与形状坐标，按原始版式在浏览器中还原。
- PDF：PyMuPDF 提取文字，并渲染页面图片作为预览。
- 支持拖拽上传、缩略图导航、翻页、缩放、点击页码跳转。
- 滚轮翻页；按住 `Ctrl / ⌘` 滚动滚轮缩放。

**智能体笔记**

- OpenAI 兼容接口流式输出，支持 OpenAI / DeepSeek / Moonshot / 通义千问 / 智谱 / Ollama / 自定义。
- 输出语言：中文 / English / 中英双语；5 级详细度：速览 → 精讲。
- 重要度三级着色：核心必记、重点理解、了解即可。
- 内置 KaTeX 本地资源，支持 `$...$`、`$$...$$`、`\(...\)`、`\[...\]`。
- 自动识别高置信度图片与图示并插入笔记；表格使用独立表格插件；模型可用 `[[VISUAL p.页码]]` 指定截图。
- 强制“改写而非照抄”，保留公式、术语与页码引用。
- 无 Key 或调用失败时可切本地摘录模式：不联网，从原文抽取要点。
- 复制 Markdown、导出 `.md`、打印 / 另存为 PDF。
- 笔记按“文档 + 语言 + 难度”缓存在浏览器，刷新后可恢复。

**学习工作区**

- 笔记 / 学习计划 / 里程碑测试 / 学习问答四个工作区，共用左侧课件预览。
- 计划：多计划并存、切换激活、删除；按页记录进度。
- 测试：按里程碑出题，提交后评分并给出解析；历史测试全部保留，可展开查看。
- 问答：基于课件检索回答并附页码引用；课件中无依据时用通用知识回答并明确标注。

## 快速开始

需要 Python 3.10+（已在 3.13 验证）。

```powershell
cd d:\learning_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 可选：配置模型（也可以启动后在网页右上角“设置”里填写）
Copy-Item .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL

.\run.ps1
# 若 PowerShell 禁止执行脚本：
# powershell -ExecutionPolicy Bypass -File .\run.ps1
# 或直接双击 run.bat
```

打开 <http://127.0.0.1:8124>，点“示例课件”或拖入自己的 PPTX/PDF。

端口默认 `8124`，可用环境变量覆盖：

```powershell
$env:PORT=9000; .\run.ps1
```

仓库自带示例：`samples/demo.pptx`（Transformer 与注意力机制，10 页）、`samples/demo.pdf`（机器学习基础，6 页）。

## 模型配置

### 方式一：网页设置（推荐）

右上角齿轮 → 选择服务商预设或自定义 → 填 API Key → 保存。

- Key 只存在浏览器 `localStorage`，每次请求随包发到本机后端，由后端调用模型接口。
- 后端不落盘、不写日志。
- 留空且 `.env` 也没有 Key 时，自动使用本地摘录模式。

### 方式二：服务端 `.env`

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
# OPENAI_TEMPERATURE=0.3
# MAX_CONTEXT_CHARS=24000
```

任意 OpenAI 兼容的 `/chat/completions` 都可用；Base URL 通常需要包含 `/v1`，模型名必须与服务商文档一致。

### 超时与并发

模型较慢或出题较慢时，可在 `.env` 调整：

```dotenv
PLAN_TIMEOUT_SECONDS=60
QUIZ_TIMEOUT_SECONDS=120
CHAT_TIMEOUT_SECONDS=30
PIPELINE_CONCURRENCY=2
```

## 检索与 Embedding（可选）

- 默认 `hybrid`：BM25 负责术语、页码和原文召回，Embedding 负责语义相近问法，按 `HYBRID_ALPHA` 融合。
- 未配置 Embedding 时降级为 BM25 + 字符 n-gram 词面扩展，即使问法与原文用词不同也尽量召回。
- 在网页设置中可切换 `keyword` / `local_vector` / `remote_api` / `hybrid`，并填写 Embedding Base URL、模型、Key、最大 token 与设备。
- `local_vector` 需额外安装：

```powershell
pip install -r requirements-vector.txt
```

- 未安装依赖或调用失败时自动回退关键词检索，问答面板会显示降级原因。
- 课件中没有依据时，问答仍会调用主模型回答，并标注“课件中未找到直接依据，以下是通用知识解释”，不编造页码。


## 使用说明

### 笔记

1. 上传或加载示例课件。
2. 右侧选择「输出语言」与「笔记难度」。
3. 点「生成笔记」，可随时停止，已生成内容保留。
4. 点笔记里的页码标签或课件截图，左侧跳到对应页。
5. 复制 / 导出 / 打印；`Ctrl/⌘ + S` 直接导出 Markdown。

### 学习计划

1. 切到「学习计划」工作区，设置总天数与每天分钟数。
2. 点「生成计划」，得到 3–8 个里程碑，覆盖全部页面。
3. 计划可切换激活、重复生成、删除；进度按页勾选。
4. 刷新后计划、进度与当前选择都会保留。

### 里程碑测试

1. 完成里程碑页面后测试按钮可用；最后一个里程碑在计划创建后即可测试。
2. 生成题目 → 选择答案 → 提交，得到分数、正确答案与解析。
3. 「显示提示」按需展开；「再测一次」强制重新出题。
4. 页面下方「全部测试记录」按里程碑列出每次成绩，点击可展开题目与解析。
5. 刷新后恢复当前里程碑与最近一次测试。

### 学习问答

1. 切到「学习问答」，直接提问，回答流式输出。
2. 有课件依据时附页码引用，点击可跳转。
3. 没有依据时用通用知识回答，并标注来源类型。
4. 历史对话按计划保存，可清空。

### 难度级别

| 级别 | 名称 | 输出特征 |
|---|---|---|
| 1 | 速览 | 5–8 条最核心考点 |
| 2 | 精简 | 按主题合并，每节 2–4 条要点 |
| 3 | 标准 | 短段落 + 分组要点，含定义、原理、公式、步骤与页码 |
| 4 | 详细 | 补充适用条件、易错点、例子 |
| 5 | 精讲 | 背景、对比、推导、考法、陷阱 + 自测题 |

### 重要度配色

- 🔴 `[核心]`：定义、公式、定理、必考结论、解题步骤
- 🟠 `[重点]`：易混淆点、高频考点、重要条件、常见错误
- 🟢 `[了解]`：背景、例子、补充说明

### 结构化排版

提示词会按内容关系选择组件，不是每次都使用：

````markdown
:::branches 并列主题
- [核心] 分支一 [p.3]
- [重点] 分支二
:::

:::pyramid 掌握层级
会推导 | 从公式解释梯度
会使用 | 能完成计算
了解 | 知道应用场景
:::

:::mindmap 注意力机制
- [核心] 输入表示
  - 词嵌入 + 位置编码
- [重点] 注意力计算
  - Q/K/V 与 softmax
:::

:::table 公式参数
| 符号 | 含义 | 形状 |
| --- | --- | --- |
| $Q$ | 查询矩阵 | $n \times d_k$ |
:::
````

### 英文笔记


## 目录结构

```
learning_agent/
├─ backend/
│  ├─ main.py            # FastAPI 路由、上传、SSE、计划/测试/问答接口
│  ├─ parser.py          # PPTX / PDF 解析与预览数据
│  ├─ pipeline.py        # 分段并发生成、按页序输出、局部降级
│  ├─ postprocess.py     # 长句/长段拆分、去套话、格式保护
│  ├─ notes.py           # 笔记提示词、5 级规则、本地摘录
│  ├─ plans.py           # 学习计划生成与校验
│  ├─ progress.py        # 计划进度
│  ├─ quiz.py            # 出题、校验、评分、缓存
│  ├─ chat.py            # 问答检索编排、引用校验、历史
│  ├─ retrieval/         # BM25、向量、混合检索
│  ├─ llm.py             # OpenAI 兼容流式客户端
│  ├─ prompts.py         # prompts/ 加载、变量替换、哈希
│  ├─ text_utils.py      # 分句、token 估算、文本工具
│  ├─ logging_utils.py   # JSON 日志与 trace
│  ├─ config.py          # .env、默认配置、服务商预设
│  └─ storage.py         # 课件与媒体存储
├─ frontend/
│  ├─ index.html
│  ├─ css/styles.css
│  ├─ vendor/katex/      # 本地 KaTeX
│  └─ js/
│     ├─ app.js          # 上传、预览、笔记 SSE、视觉截取
│     ├─ learning.js     # 计划、进度、测试、问答
│     └─ markdown.js     # Markdown/LaTeX/重要度/页码渲染
├─ prompts/              # 笔记、计划、测试、问答提示词与规则
├─ samples/              # 示例课件
├─ data/                 # 运行时数据（git 忽略）
├─ requirements.txt
├─ requirements-vector.txt
├─ run.ps1
└─ run.bat
```

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 服务商预设、参考价、难度、上传限制、检索与 Pipeline 状态 |
| POST | `/api/upload` | multipart 上传 `.pptx` / `.pdf` |
| POST | `/api/demo?kind=pptx\|pdf` | 加载内置示例 |
| GET | `/api/doc/{doc_id}` | 解析结果与预览数据 |
| GET | `/api/docs` | 文档列表 |
| DELETE | `/api/doc/{doc_id}` | 删除文档及其计划、进度、测试、索引 |
| POST | `/api/notes/stream` | SSE 流式生成笔记 |
| GET | `/api/doc/{doc_id}/pages/{n}.png` | PDF 页面图片 |
| GET | `/api/doc/{doc_id}/media/{name}` | 内嵌图片 / 视觉裁剪图 |
| POST | `/api/plan` | 创建学习计划 |
| GET | `/api/doc/{doc_id}/plans` | 计划列表与激活计划 |
| GET | `/api/plan/{plan_id}` | 计划详情 |
| POST | `/api/plan/{plan_id}/activate` | 激活计划 |
| DELETE | `/api/plan/{plan_id}` | 删除计划及其进度与测试 |
| GET | `/api/progress/{doc_id}/{plan_id}` | 计划进度 |
| POST | `/api/progress/{doc_id}/{plan_id}/page` | 标记页面完成 / 未完成 |
| POST | `/api/quiz` | 生成或读取缓存测试 |
| GET | `/api/quiz/{quiz_id}` | 获取测试 |
| POST | `/api/quiz/{quiz_id}/submit` | 提交答案并评分 |
| GET | `/api/quiz/history` | 测试历史 |
| POST | `/api/chat/stream` | SSE 流式问答 |
| GET / DELETE | `/api/chat/history` | 读取 / 清空聊天历史 |
| GET | `/api/retrieval/config` | 检索模式与索引状态 |
| POST | `/api/retrieval/rebuild` | 重建索引 |
| POST | `/api/retrieval/check` | 召回自检 |

`POST /api/notes/stream` 请求示例：

```json
{
  "doc_id": "abcdef123456",
  "language": "bilingual",
  "level": 3,
  "force_local": false,
  "api": {
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-...",
    "model": "deepseek-chat"
  }
}
```

SSE 事件类型：`meta`、`status`、`notice`、`delta`、`done`、`error`。

## 数据与隐私

- 课件、计划、进度、测试结果与聊天记录保存在本机 `data/`，不上传任何服务器。
- 除调用你配置的模型接口外，应用不发其他外部请求。
- 删除课件会一并清理其计划、进度、测试与索引。
- 导出 Markdown 与打印仅使用当前笔记内容。

## 常见问题

**生成的是本地摘录，不是模型结果**

没有可用 Key，或模型调用失败后走了降级。检查设置里的 Base URL（通常需含 `/v1`）、模型名与 Key，再看顶部提示的失败原因。本地摘录不做翻译与改写。

**计划或测试提示“回退”**

模型超时或返回内容不符合结构要求。可提高 `PLAN_TIMEOUT_SECONDS` / `QUIZ_TIMEOUT_SECONDS`，或换响应更快的模型；旧的回退结果需要重新生成。

**问答回答“课件中未找到直接依据”**

检索没有命中相关页面，已改用通用知识回答。确认课件有可提取文字（扫描版 PDF 无 OCR），或换用更贴近原文的提问方式。

**端口被占用**

```powershell
$env:PORT=9000; .\run.ps1
```

**扫描版 PDF 没有笔记**

图片型 PDF 无 OCR，只能预览，无法提取文字生成笔记。

## 已知限制

- PPTX 预览是基于形状坐标的 HTML 还原，不是 PowerPoint 像素级渲染；复杂 SmartArt、图表、动画、主题字体可能有差异。
- 视觉截取只针对高置信度图片/图示；重复 logo、装饰图、满版背景会被过滤。
- 费用徽标为参考估算，不构成账单。
- 旧版 `.ppt` 不支持，请另存为 `.pptx`。
- 单文件默认上限 50 MB、200 页；超长课件按上下文预算截断并在界面提示。
- 本地摘录模式为抽取式，可能保留原句结构。

英文模式使用独立提示词：每条 bullet ≤18 words、段落 ≤2 句；并列点较多时使用 `:::branches`。模型仍输出平铺列表时，前端会兜底包装并拆分超长段落。
