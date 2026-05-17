# Peppa 项目技术架构

## 目标

Peppa 是一个长期运行的 AI agent。它需要支持 CLI、Telegram 等第三方入口，但在开发和调试阶段，最重要的入口是一个本地运行的开发者调试台。

调试台不是面向普通使用者的产品界面，而是用于观察、分析和优化 agent 行为的内部工具。它应该清晰、信息展示合理、操作方便，并使用深色主题。

项目的核心难点不是工具数量，而是记忆系统、模型行为、上下文组织、调试可见性和长期稳定运行。因此，开发过程需要小步迭代，每个功能都应有清晰的展示和验证方式。

## 技术选型

核心语言使用 Python，前端调试台使用 TypeScript、React 和 Vite。

推荐技术栈：

| 模块 | 技术 |
| --- | --- |
| Agent 核心 | Python |
| 本地 API 服务 | FastAPI |
| CLI | Typer |
| 本地数据库 | SQLite |
| 前端调试台 | TypeScript + React + Vite |
| 包管理 | uv |
| 模型调用 | OpenAI-compatible 外部 API |

项目不依赖本地模型，不依赖 embedding，不依赖 CUDA、PyTorch、本地向量数据库或其他重型本地 AI 运行环境。默认安装和运行应保持轻量。

## 总体架构

Peppa 的核心逻辑应集中在 agent core 中。CLI、Web 调试台、Telegram 等入口不直接实现 agent 行为，而是通过统一的 gateway 转换成标准输入，再交给核心流程处理。

```text
CLI / Web Debug Console / Telegram
        |
        v
gateway: 标准化输入
        |
        v
agent core
        |
        +--> memory
        +--> skills
        +--> tools
        +--> model client
        |
        v
trace / response / state update
```

这样的设计可以保证不同入口共享同一套行为逻辑，也方便在本地调试台中复现和分析 agent 的完整处理过程。

## 推荐目录结构

```text
peppa-agent/
  config.toml
  config.example.toml

  docs/
  skills/
  tools/
  prompts/

  state/
    peppa.sqlite3

  var/
    logs/
    traces/
    cache/
    runtime/

  src/peppa/
    config/
    models/
    core/
    memory/
    runtime/
    gateway/
    adapters/
    api/
    cli/

  web/
  scripts/
```

## 版本化与忽略规则

应该提交到 git 的内容：

- `docs/`
- `skills/`
- `tools/`
- `prompts/`
- `config.example.toml`
- 源代码
- 安装脚本、启动脚本和测试代码

不应该提交到 git 的内容：

- `config.toml`
- `state/`
- `var/`
- SQLite 数据库文件
- 日志、trace、缓存、临时运行状态

虽然 `state/` 和 `var/` 都不提交到 git，但二者语义不同，不能混为一类。

## 长期状态与可清理数据

`state/` 存放 Peppa 的长期状态。`state/peppa.sqlite3` 是基础数据文件，用于保存会话历史、长期记忆、事件记录和 agent 的身份连续性。

删除 `state/peppa.sqlite3` 等同于删除 Peppa 的历史行为和特有身份，应被视为重置 agent。

`var/` 存放可清理的运行辅助数据，例如日志、trace、缓存和临时 runtime 状态。删除 `var/` 通常只会影响调试信息和缓存，不应删除 agent 的长期记忆。

后续如果实现清理命令或调试台清理功能，必须明确区分：

- 清理日志、trace、缓存：操作 `var/`
- 重置 agent：操作 `state/peppa.sqlite3`，并且需要明显确认

## 配置文件

真实配置文件放在项目根目录：

```text
config.toml
```

该文件不提交到 git，用于保存本地模型配置、API key 和运行配置。

项目根目录同时提供示例配置：

```text
config.example.toml
```

示例配置提交到 git。模型配置尽量保持简单，每个模型只包含必要字段。

```toml
[app]
default_model = "model-a"

[[models]]
model = "model-a"
base_url = "https://api.example-a.com/v1"
api_key = "replace-me"
tool_adapter = "auto"

[[models]]
model = "model-b"
base_url = "https://api.example-b.com/v1"
api_key = "replace-me"
tool_adapter = "auto"

[[models]]
model = "model-c"
base_url = "https://api.example-c.com/v1"
api_key = "replace-me"
tool_adapter = "auto"
```

`model` 同时作为：

- 调用外部 API 时传入的模型名
- 调试台中展示的模型名称
- 系统内部选择模型的标识

因此，同一个 `config.toml` 中的 `model` 应保持唯一。

第一阶段不考虑一个 `base_url` 对应多个模型的情况。以后如果确实需要区分展示名和模型名，可以再增加可选字段。

`tool_adapter` 用于指定 tool call 的请求和返回解析适配方式。它只处理不同 provider 在 tool call 协议上的差异，不包含任何 memory schema 或业务逻辑。

可选值包括：

- `auto`：根据 `base_url` 和 `model` 自动判断
- `openai`：标准 OpenAI-compatible 行为
- `deepseek`：DeepSeek tool call 行为
- `qwen` / `dashscope`：Qwen DashScope tool call 行为
- `kimi` / `moonshot`：Kimi Moonshot tool call 行为

## 模型调用

Peppa 只调用 OpenAI-compatible 的外部模型 API。不同模型可以有不同的 `base_url` 和 `api_key`。

模型客户端应隐藏 API key，不应通过前端接口把完整 key 返回给调试台。调试台最多展示模型名、base URL 和 key 是否已配置。

虽然这些模型整体都兼容 OpenAI 的 chat completions 风格，但 tool call 的细节可能不同。因此模型调用层包含一个通用 tool-call adapter：

- 普通对话仍然通过统一的 `ModelClient` 发送
- 如果请求携带 `tools`，adapter 负责添加 provider 所需的最小参数
- adapter 负责把 provider 返回的 `tool_calls` 解析成统一结构
- memory、tools、runtime 等业务模块只消费统一后的 tool call，不直接解析 provider 原始格式

当前 provider 差异：

- DeepSeek：使用标准 OpenAI-compatible `tools` / `tool_choice` / `message.tool_calls`
- Qwen：tool-call 请求默认关闭 thinking，避免结构化参数受思考模式干扰；如果返回的 arguments 存在多重引号转义或缺失 JSON 值，会在 qwen adapter 内做轻量修复
- Kimi：tool schema 默认设置 `strict = false`，`kimi-k2.6` 的 tool-call 请求默认关闭 thinking

adapter 不硬编码 memory schema。记忆抽取、工具执行或未来其他功能都可以传入自己的 tool schema，并复用同一套 provider 适配和返回解析。

调试台顶部应提供方便的模型切换控件。切换模型后：

- 后续请求默认使用选中的模型
- 每次模型调用都记录实际使用的模型
- 历史 trace 不受影响
- 单次请求未来可以支持覆盖默认模型

## 记忆系统方向

Peppa 的记忆系统是项目核心。由于项目不使用 embedding，记忆系统不应设计成传统 RAG 形态。

记忆系统的目标不是只把内容保存下来，而是形成可回忆、可追溯、可改变后续行为的长期能力。当前阶段已经优先完成“记住”的主体框架，后续开发应围绕让记忆真正被使用形成闭环。

Peppa 的长期状态应遵循一个底层原则：凡是会被持久化、用于召回、排序、决策或调试的数据，都必须是人可以读懂、检查和迁移的数据形态。模型可以在单次调用中进行临时判断和推理，但不能把某个模型不可解释的中间表示作为长期记忆的基础设施。这样才能把记忆、推理和模型能力分开，避免系统被绑定到某个特定模型生成的向量空间或隐藏表示。

长期信息分为几层：

- 原始经历：按时间保留用户输入、模型输出、系统决策、记忆写入、工具调用等完整 trace
- 语义图谱：从经历中沉淀出的 node、edge 和 source，用于表达稳定的人、项目、概念、事件、偏好和关系
- 联想标签：用人类可读的 tag 作为回忆入口，替代不可解释且绑定模型的向量
- 精确外置记忆：项目规则、技术决策、任务状态、设计细节等进入文档、任务记录或其他外部载体，语义图只保留索引
- skill 化记忆：反复出现、会影响未来工作的项目经验或流程，可以从具体记忆和示例中固化为 skill，让记忆直接改变后续行为

调试台应该能展示一次 agent 处理过程中的关键信息：

```text
用户输入
  -> 检索到的记忆
  -> 拼接进 prompt 的上下文
  -> 模型请求参数
  -> 模型输出
  -> 是否产生新记忆
```

目标是让 agent 行为可观察、可解释、可迭代。

短期开发重点不应继续过度细化记忆本体，而应优先完成以下闭环：

- 补齐精确外置层，先让 `document_suggestions` 能实际指导文档更新，后续再考虑 skill 候选
- 增加基础图谱维护能力，例如 node 合并、摘要更新、别名或 tag 合并、冲突和覆盖处理
- 实现第一版 recall：输入内容生成或匹配联想 tag，再从 tag 命中 node/edge，必要时展开 source、document 或 skill，最后组装进 memory context
- 在 recall 可用之前，暂缓复杂主体视角建模和资源积分等自我评估系统

## 本地调试台

本地调试台是开发阶段最重要的界面，定位为开发者调试工具，而不是普通用户聊天产品。

调试台应使用深色主题，并优先展示对优化 agent 行为有帮助的信息，例如：

- 当前模型
- runtime 状态
- 最近会话
- 用户输入和模型输出
- 检索到的记忆
- prompt 组成
- 模型调用参数
- trace
- 新增或更新的记忆
- 错误和日志摘要

第一阶段不做登录鉴权。服务默认只绑定本地地址，例如 `127.0.0.1`。

## 分发与安装

最终目标是支持类似下面的安装方式：

```bash
curl -fsSL https://example.com/install.sh | bash
```

安装过程应保持轻量，避免默认安装重型依赖。默认安装不应包含本地大模型、CUDA、PyTorch 或大型向量数据库。

安装脚本未来可以负责：

- 检测或安装 `uv`
- 下载项目代码或 release 包
- 创建 Python 虚拟环境
- 安装依赖
- 复制或生成 `config.toml`
- 初始化 `state/` 和 `var/`
- 安装 `peppa` 命令

## 第一阶段边界

第一阶段目标是搭建一个最小但方向正确的骨架，而不是一次性实现完整 agent。

建议第一阶段完成：

- Python 项目结构
- `config.toml` 和 `config.example.toml`
- `.gitignore` 规则
- CLI 启动命令
- FastAPI 本地服务
- React/Vite 深色调试台
- SQLite 初始化
- 简单对话请求
- 模型切换
- 基础 trace 记录和展示

第一阶段暂不实现：

- Telegram 接入
- 复杂 tools 系统
- 复杂定时任务系统
- 完整长期记忆演化
- 本地模型
- embedding
- 向量数据库
- 多用户账号系统

## 开发原则

开发过程遵循以下原则：

- 先讨论需求和实现方式，达成共识后再开发
- 不确定的产品逻辑、模型行为和数据结构先提问
- 每次迭代跨度合理，不一次性推进过大
- 每个功能都应有清晰展示或验证方式
- 代码保持清晰、简洁、直观
- 如果有简单可靠的实现方式，就优先使用简单方式
- 只有在确实降低复杂度或匹配现有结构时才引入抽象
- 重视 agent 行为调试，而不只是功能接通
