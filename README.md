# 课堂笔记智能体 · Lecture Notes Agent

上传 PPTX 或 PDF 课件，左侧保留原始版式预览，右侧由智能体流式生成学生笔记式的知识点总结：精简改写、中/英/双语、5 级详细度、按重要度着色、标注来源页码。

同一页面还提供笔记章节勾选、章节测试与基于课件的问答。

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

- 笔记 / 章节测试 / 学习问答三个工作区，共用左侧课件预览。
- 章节：笔记里的 `##` 小节即学习章节，自带页码范围；在笔记标题前勾选完成，顶部显示完成进度，刷新后保留。
- 测试：只对已勾选章节出题，题源只取该章节页面；中文 / 英文出题可选，约 40% 为应用题（新情境、案例与推理），其余为概念辨析题；题目带「应用题 / 辨析题」标签，提交后评分并给出解析；历史测试全部保留，可展开查看。
- 问答：基于课件检索回答并附页码引用；课件中无依据时用通用知识回答并明确标注。

**内容边界**

- 笔记与题目只保留课程知识，自动跳过课程安排、周次/讲次编号、考核方式、成绩构成、打分与评分标准、考试时间地点与复习范围、出勤与作业截止、教材与参考书、联系方式、课程目标等事务性内容。
- 出题不会出现“本页讲了什么/本讲主题是什么”这类记忆题，也不会把页码写进题干。

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

模型较慢或出题风格偏保守时，可在 `.env` 调整：

```dotenv
# 出题温度：0.6 稳定保守，0.8 情景题更灵活（默认），1.0 以上容易返回不合格 JSON
QUIZ_TEMPERATURE=0.8
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

### 章节勾选

1. 先生成笔记，笔记里的每个 `##` 小节会自动注册为一个章节，页码范围取自小节内的 `[p.页码]`。
2. 每个小节标题左侧有勾选框，右侧有「生成测试」按钮；勾选表示已学完，底部显示「章节 3/6 已完成」。
3. 点「生成测试」会跳到「章节测试」、自动勾选该章节并直接出题；若章节还没注册成功会提示原因。
4. 勾选状态按「文档 + 语言 + 难度」保存在本机，刷新或重新打开后恢复。
5. 重新生成笔记时，标题与页码范围一致的章节会沿用原来的勾选。

### 章节测试

1. 切到「章节测试」，下拉框与章节标签只列出已勾选的章节（默认「全部已勾选章节」），未勾选的章节以灰色「未勾选」标签提示。
2. 选择题数、难度与出题语言（中文题 / English），点「生成测试」。出题语言默认跟随笔记语言：英文笔记默认出英文题。
3. 题目按约 40% 应用题 + 60% 辨析题生成；应用题会换新情境或数据，不从课件原文挖空。
4. 未勾选的章节无法出题：后端会返回“请先在笔记中勾选完成”。
5. 作答 → 提交，得到分数、正确答案与解析；「显示提示」按需展开；「再测一次」强制重新出题。
6. 页面下方「全部测试记录」按章节列出每次成绩，点击可展开题目与解析。
7. 刷新后恢复最近一次测试与历史记录。

> 没有配置模型时会退化为「课件原文比对题」：题干按所选语言生成，但选项保留课件原文语言，并在提示中说明。

### 学习问答

1. 切到「学习问答」，直接提问，回答流式输出。
2. 有课件依据时附页码引用，点击可跳转。
3. 没有依据时用通用知识回答，并标注来源类型。
4. 历史对话按课件保存，可清空。

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
│  ├─ main.py            # FastAPI 路由、上传、SSE、章节/测试/问答接口
│  ├─ parser.py          # PPTX / PDF 解析与预览数据
│  ├─ pipeline.py        # 分段并发生成、按页序输出、局部降级
│  ├─ postprocess.py     # 长句/长段拆分、去套话、过滤事务性小节
│  ├─ notes.py           # 笔记提示词、5 级规则、本地摘录
│  ├─ sections.py        # 章节注册、勾选进度、页码范围
│  ├─ progress.py        # 聊天历史存储
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
│     ├─ app.js          # 上传、预览、笔记 SSE、视觉截取、章节勾选
│     ├─ learning.js     # 章节测试、问答
│     └─ markdown.js     # Markdown/LaTeX/重要度/页码渲染 + 章节解析
├─ prompts/              # 笔记、测试、问答提示词与规则
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
| DELETE | `/api/doc/{doc_id}` | 删除文档及其章节、测试、聊天记录、索引 |
| POST | `/api/notes/stream` | SSE 流式生成笔记 |
| GET | `/api/doc/{doc_id}/pages/{n}.png` | PDF 页面图片 |
| GET | `/api/doc/{doc_id}/media/{name}` | 内嵌图片 / 视觉裁剪图 |
| POST | `/api/sections` | 注册 / 更新笔记章节（签名=语言-难度 + 章节列表） |
| GET | `/api/sections?doc_id=&signature=` | 章节与勾选状态 |
| POST | `/api/sections/{doc_id}/toggle` | 勾选 / 取消勾选章节 |
| POST | `/api/quiz` | 生成或读取缓存测试（仅已勾选章节） |
| GET | `/api/quiz/{quiz_id}` | 获取测试 |
| POST | `/api/quiz/{quiz_id}/submit` | 提交答案并评分 |
| GET | `/api/quiz/history?doc_id=&signature=` | 测试历史 |
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

- 课件、章节勾选、测试结果与聊天记录保存在本机 `data/`，不上传任何服务器。
- 除调用你配置的模型接口外，应用不发其他外部请求。
- 删除课件会一并清理其章节、测试、聊天记录与索引。
- 旧版本留下的 `data/*/plans/`、`data/*/progress/local/plan_*.json` 与没有 `signature` 字段的旧测试记录不再读取，可直接删除。
- 导出 Markdown 与打印仅使用当前笔记内容。

## 常见问题

**生成的是本地摘录，不是模型结果**

没有可用 Key，或模型调用失败后走了降级。检查设置里的 Base URL（通常需含 `/v1`）、模型名与 Key，再看顶部提示的失败原因。本地摘录不做翻译与改写。

**笔记标题前没有勾选框 / 章节测试下拉为空**

说明章节清单没有注册成功。常见原因：后端进程还是旧版本（没有 `/api/sections` 路由，注册会失败并提示 `HTTP 404`），或浏览器仍在使用旧 JS。处理：停掉后端重新运行 `.\run.ps1`，并在页面上按 `Ctrl + F5` 强制刷新。笔记底部与章节测试面板会直接显示失败原因。

**测试提示“原文比对题”**

模型超时或返回的题目不符合要求。常见判负原因：题干或选项出现课程事务（安排、考核、打分、考试、教材）或元问题（今天学了什么、本页讲了什么）、题干出现页码、空泛题干（“以下哪项正确”）、解释未标注依据页、应用题数量不足。系统会自动重试并把这些原因显示在提示里。可提高 `QUIZ_TIMEOUT_SECONDS`，或把 `QUIZ_TEMPERATURE` 调到 0.6–0.7 让输出更稳定；旧的回退结果需要重新生成。

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
