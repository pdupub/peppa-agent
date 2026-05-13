# Peppa 最小调试闭环

## 背景

第一个版本的目标不是实现完整 agent，而是搭建一个可以运行、可以观察、可以继续调优的最小闭环。

这个版本需要证明以下事情：

- 本地配置可以管理多个 OpenAI-compatible 模型
- CLI 和 Web API 可以走同一条 agent 调用路径
- 本地 SQLite 可以记录会话与 trace
- 深色调试台可以展示模型切换、输入输出和调试信息
- 项目不依赖本地模型、embedding 或重型 AI 运行环境

## 范围

本版本包含：

- Python 项目骨架
- `config.toml` 本地真实配置
- `config.example.toml` 示例配置
- `.gitignore` 忽略本地配置、长期状态和运行辅助数据
- SQLite 初始化
- CLI 命令
- FastAPI 本地服务
- OpenAI-compatible 模型客户端
- React/Vite 深色调试台
- 模型切换
- 基础 trace 记录和展示

本版本不包含：

- Telegram 接入
- 复杂 tools 系统
- 复杂 skills 执行
- 长期记忆提炼与演化
- 定时任务系统
- 多用户登录
- embedding 或向量检索

## 本地文件约定

真实配置：

```text
config.toml
```

该文件不提交到 git。

示例配置：

```text
config.example.toml
```

该文件提交到 git，但不包含真实 API key。

长期状态：

```text
state/peppa.sqlite3
```

该文件保存会话、trace 和未来的长期记忆。删除它等同于重置 Peppa 的历史和身份连续性。

可清理运行数据：

```text
var/
```

该目录用于日志、缓存、临时 trace 文件和 runtime 状态。

## 调试台展示

调试台第一版包含：

- 顶部模型切换控件
- runtime 与 SQLite 状态
- 输入框
- 用户输入展示
- 模型输出展示
- 最近 trace 列表
- prompt JSON
- memory hits JSON
- request JSON
- response JSON

当前版本的 `memory_hits` 为空数组，这是有意保留的展示位置。后续实现记忆检索后，调试台可以直接展示检索结果。

## 验收方式

可以通过以下方式验证第一版：

```bash
peppa models
peppa reset-agent
peppa chat "请用一句话确认 Peppa 是否可用。"
peppa serve
```

`peppa serve` 和 `peppa chat` 会在需要时自动创建数据库和表结构。`peppa reset-agent` 用于重置 Peppa 的长期状态：如果数据库不存在，会直接创建；如果数据库已存在，会先在命令行要求确认。

启动服务后访问：

```text
http://127.0.0.1:8000
```

也可以通过 API 验证：

```text
GET /api/health
GET /api/config
POST /api/chat
GET /api/traces
```

## 已知取舍

模型请求默认使用 `temperature = 1.0`。这是为了兼容当前配置中的不同 OpenAI-compatible provider，其中有模型只接受该值。

数据库层第一版直接使用 Python 标准库 `sqlite3`，不引入 ORM。这样代码更直观，也方便在记忆系统真正复杂起来之前保持低抽象。

前端使用 Vite 6，而不是更新的 Vite 7/8。这样可以兼容当前本地 Node 版本，同时避免 npm audit 中的已知漏洞。
