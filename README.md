# ui-mono

Python 原生实现的 coding agent CLI MVP，参考 pi-mono 的核心链路与设计取舍：最小工具集、显式运行时、可恢复会话、上下文压缩，以及能被验证的端到端演示路径。

## 当前能力

- Anthropic provider 适配，模型调用与工具 schema 解耦。
- `AgentSessionRuntime` 负责 turn 编排、tool calling、summary / compaction、session 写入。
- **runtime JSON stream** 与 **session event log** 已明确区分：
  - runtime JSON stream：面向运行期观察，统一使用 `event / timestamp / session_id / payload`
  - session event log：面向持久化恢复，使用 JSONL 保存 `session` / `message` / `tool_call` / `tool_result` / `tool_error` / `branch` / `compaction`
- session snapshot 恢复、branch/fork、session tree 构建。
- 本地工具集：`read` / `write` / `edit` / `bash` / `ls` / `find` / `grep`。
- 工作目录边界保护与 surrogate 字符清洗。
- 集中式 shell 命令安全策略（`ShellCommandPolicy`）：三级裁决（`ALLOW / REQUIRE_APPROVAL / DENY`），高危命令直接拒绝，中风险命令在 `chat` 交互模式下触发 `typer.confirm()`，headless 模式（`run / rpc / code-demo / demo`）自动拒绝。
- 脚本化 demo 模型（`demo` / `code-demo`）与真实 Anthropic 模型（`chat` / `run` / `rpc`）并存，前者不消耗 API 额度。

## 架构概览

```text
CLI commands
  ├─ chat                  真实模型对话入口 + 内置内省命令（需 ANTHROPIC_API_KEY）
  ├─ run                   headless 一次性执行（需 ANTHROPIC_API_KEY）
  ├─ rpc                   JSONL 长连接模式（需 ANTHROPIC_API_KEY）
  ├─ demo                  脚本化 runtime 演示（无需 API key）
  ├─ code-demo             脚本化编程闭环演示（无需 API key）
  ├─ inspect-session       验证 resume / branch / compaction
  ├─ sessions-list         浏览 session 列表
  ├─ sessions-summary      查看最新摘要
  └─ sessions-tree         浏览 session 树

AgentSessionRuntime
  ├─ build_branch_messages()
  ├─ model_client.generate()
  ├─ tool execution + tool_error recovery
  ├─ unified runtime stream events
  └─ compaction summary + kept history replay

SessionStore (JSONL)
  ├─ create / append / read_events
  ├─ load_snapshot / load_history
  ├─ list_paths / latest
  ├─ fork
  └─ build_tree
```

对应代码入口：

- 运行时：[src/ui_mono/runtime/agent_session.py](src/ui_mono/runtime/agent_session.py)
- 会话存储：[src/ui_mono/session/store.py](src/ui_mono/session/store.py)
- CLI：[src/ui_mono/cli.py](src/ui_mono/cli.py)
- 工具注册：[src/ui_mono/app.py](src/ui_mono/app.py)

## 安装

```bash
pip install -e .[dev]
```

## 配置真实模型对话

`chat` 命令会按以下顺序加载凭据：

1. 当前工作目录 `.env`
2. 进程环境变量
3. `~/.claude/config.json` 中的 `env`

至少需要其一：

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`

## 1. 稳定端到端演示

这是目前最适合放到简历或答辩里的稳定 demo，**不依赖外部模型服务，也不消耗 API 额度**。

> **说明：`demo` 和 `code-demo` 命令使用脚本化模型（`SequenceModelClient` / `build_code_demo_model`），其"模型响应"是预先硬编码的固定脚本，不经过任何真实 LLM。** 它们的目的是稳定复现整条 runtime 链路（工具调用、事件流、tool_error 恢复、runtime JSON stream），而不是展示模型智能。如需验证真实 Anthropic 模型连通性，请参考 [第 3 节](#3-真实聊天入口)。

### 1.1 通用 runtime 演示

```bash
ui-mono demo --cwd .
ui-mono demo --cwd . --json
ui-mono demo --cwd . --json-stream
```

现在 `--json-stream` 已经是**真实流式输出**：assistant 的 `message_update.delta` 会分多次发出，而且 `message_update` 本身只携带增量片段；完整文本会在 `message_end.content` 和 `turn_end.turn.reply` 中给出。对于仅触发 tool call、没有任何可见文本的中间回合，runtime stream 不会再额外发出空白 assistant `message_start / message_update / message_end` 事件。

这个命令会按固定脚本完成：

1. `write demo-notes.txt`
2. `read demo-notes.txt`
3. `edit demo-notes.txt`
4. `grep demo-notes.txt`
5. 故意读取不存在的 `missing.txt`

你会在输出里看到：

- 正常的 `tool_call` / `tool_result`
- 明确的 `tool_error`
- `--json-stream` 下的逐事件 runtime stream（如 `turn_start`、`message_start`、`message_update`、`tool_execution_start`、`tool_execution_end`、`turn_end`），并使用更标准的 payload 结构：
  - `turn_start` / `turn_end` → `payload.turn`
  - `message_update` → `payload.message.delta`（只发增量，不重复携带全文）
  - `message_end` → `payload.message.content`（给出该条消息的完整内容）
  - `tool_execution_*` → `payload.tool` + `payload.result`

### 1.2 编程任务闭环演示

```bash
ui-mono code-demo --cwd .
ui-mono code-demo --cwd . --json
ui-mono code-demo --cwd . --json-stream
```

这个命令会在 `.ui-mono-code-demo/` 下构造一个最小 Python 修 bug 场景，并复用同一套 runtime 跑完整 coding loop：

1. `read calculator.py`
2. `read test_calculator.py`
3. `bash` 运行 pytest，先观察失败
4. `edit calculator.py` 修复 bug
5. `bash` 再次运行 pytest，确认通过

输出里会包含：

- 两次 `bash` 测试执行结果（先失败、后通过）
- 被修复的源码文件路径
- 最终 assistant reply
- 完整 runtime 事件流（`--json-stream`）

这条演示更适合拿来说明：`ui-mono` 已经不只是“会调工具”，而是能稳定展示最小 `read → edit → test → fix → retest` 编程闭环。

### 1.3 shell 安全边界

当前文件工具和 shell 工具都受边界控制：

- `read` / `write` / `edit` 继续受工作目录边界保护，禁止路径逃逸
- `bash` 在执行前会经过集中式 shell policy
- 明显危险的命令（如 `rm -rf`、`shutdown`、破坏性 git reset/clean 等）会被直接拒绝
- 被拒绝的 shell 调用会进入 `tool_error` 和 runtime stream，便于调试与审计

这让 `ui-mono` 的 coding demo 不只是“能跑起来”，而是已经具备最小 guardrails。

一个最小示例大概长这样：

```jsonl
{"event":"turn_start","timestamp":"2026-04-12T10:00:00.000Z","session_id":"sess_123","payload":{"turn":{"input":"read README"}}}
{"event":"message_start","timestamp":"2026-04-12T10:00:00.010Z","session_id":"sess_123","payload":{"message":{"role":"assistant","kind":"response"}}}
{"event":"message_update","timestamp":"2026-04-12T10:00:00.020Z","session_id":"sess_123","payload":{"message":{"role":"assistant","delta":"I can"}}}
{"event":"message_update","timestamp":"2026-04-12T10:00:00.030Z","session_id":"sess_123","payload":{"message":{"role":"assistant","delta":" help"}}}
{"event":"message_update","timestamp":"2026-04-12T10:00:00.040Z","session_id":"sess_123","payload":{"message":{"role":"assistant","delta":" with that."}}}
{"event":"message_end","timestamp":"2026-04-12T10:00:00.050Z","session_id":"sess_123","payload":{"message":{"role":"assistant","kind":"response","content":"I can help with that."}}}
{"event":"turn_end","timestamp":"2026-04-12T10:00:00.060Z","session_id":"sess_123","payload":{"turn":{"reply":"I can help with that.","summary":null}}}
```

这里要注意：连续多个 `message_update` 是正常的，因为模型流式输出本来就会把一句话拆成多个增量片段；真正的完整文本要看 `message_end.content` 或 `turn_end.turn.reply`。如果某一轮只有 `tool_use`、没有用户可见文本，那么这轮不会输出空白 assistant 消息事件。

演示重点是：`ui-mono` 不只是“能调工具”，而是已经具备**成功路径 + 失败路径**的事件记录能力。

## 2. 验证 resume / branch / compaction

```bash
ui-mono inspect-session --cwd .
ui-mono inspect-session --cwd . --json
ui-mono inspect-session --cwd . --json-stream
```

这个命令会自动：

1. 创建 base session
2. 连续运行多轮触发 compaction
3. fork 出 `experiment` 分支
4. 在分支上继续一轮对话
5. 重新从 session store 读取 snapshot
6. 输出 session tree、summary 和恢复后的 history 大小

重点看这几行：

- `compaction seen: True`
- `branch event seen: True`
- `branch summary: ...`
- `session tree:`

它对应 pi-mono 里“会话不是线性日志，而是可恢复、可分叉的历史树”这一核心思想。

## 3. 真实聊天入口

> **`chat` / `run` / `rpc` 命令调用真实 Anthropic 模型，需要设置 API key。** 与 `demo` / `code-demo` 不同，这里的响应由实际 LLM 生成。

### 3.0 设置凭据并验证连通性

```bash
# 1. 设置 API key（任选其一）
export ANTHROPIC_API_KEY=sk-ant-...          # 直接写入环境变量
# 或在当前目录创建 .env 文件：
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env

# 2. 验证真实模型连通性（最小 smoke test）
ui-mono run --cwd . --prompt "Say hello in one sentence"
ui-mono run --cwd . --prompt "Say hello in one sentence" --json
ui-mono run --cwd . --prompt "Say hello in one sentence" --json-stream
```

如果输出包含模型回复，说明凭据和网络均正常。

> Windows 控制台提示：CLI 输出已统一按 UTF-8 写入，`run/chat/rpc` 在包含中文或 emoji（如 👋）时不会再因默认 GBK 编码抛出 `UnicodeEncodeError`。

```bash
ui-mono chat --cwd .
ui-mono chat --cwd . --resume
ui-mono chat --cwd . --model claude-opus-4-6
ui-mono chat --cwd . --json-stream
```

## 3.1 headless 一次性执行

```bash
ui-mono run --cwd . --prompt "read README"
ui-mono run --cwd . --prompt "read README" --json
ui-mono run --cwd . --prompt "read README" --json-stream
```

这个模式适合脚本、CI 或一次性调用：执行一轮 prompt，输出结果后退出。

交互内支持：

- `/branch <label>`：从当前 session fork 一个新分支
- `/summary`：以 runtime inspect event 输出当前 session 的最新摘要
- `/inspect`：以 runtime inspect event 输出当前 session 的 header / summary / compaction 状态
- `/tree`：以 runtime event 输出当前所有 session 的树结构
- `/sessions`：以 runtime event 输出当前可浏览的 session 列表
- `/quit`：退出

其中 `--json-stream` 下的 chat 内省输出也统一走 runtime schema：

- `inspect_summary` → `payload.inspect`
- `inspect_session` → `payload.inspect`
- `session_tree` → `payload.tree`
- `session_list` → `payload.sessions`
- `branch_created` → `payload.branch`

## 4. session 浏览命令

```bash
ui-mono sessions-list --json
ui-mono sessions-summary --json
ui-mono sessions-tree --json

ui-mono sessions-list --json-stream
ui-mono sessions-summary --json-stream
ui-mono sessions-tree --json-stream

ui-mono sessions-list --cwd . --demo --json
ui-mono sessions-summary --cwd . --demo --json
ui-mono sessions-tree --cwd . --demo --json
ui-mono sessions-list --cwd . --demo --json-stream
```

这些命令补的是更接近 pi-mono 的“可浏览 session 状态”，而不是只有 `--resume` 一条路径。

- `--json`：输出命令结束后的结构化汇总对象
- `--json-stream`：输出单条 runtime-style 观察事件

## 4.1 RPC / JSONL 模式

```bash
ui-mono rpc --cwd .
```

启动后从 stdin 逐行读取 JSON 命令，并向 stdout 写出 JSONL：

- runtime stream event
- `rpc_response`
- `rpc_error`

其中 runtime stream 与 `run --json-stream` 保持一致：

- `message_update` 只输出增量 `delta`
- `message_end` 输出完整消息 `content`
- `turn_end` 输出最终回复 `payload.turn.reply`
- 纯 `tool_use` 中间回合不会输出空白 assistant 消息事件

示例输出片段：

```jsonl
{"event":"message_update","timestamp":"2026-04-12T10:00:00.020Z","session_id":"sess_123","payload":{"message":{"role":"assistant","delta":"read"}}}
{"event":"message_update","timestamp":"2026-04-12T10:00:00.030Z","session_id":"sess_123","payload":{"message":{"role":"assistant","delta":" README"}}}
{"event":"message_end","timestamp":"2026-04-12T10:00:00.040Z","session_id":"sess_123","payload":{"message":{"role":"assistant","kind":"response","content":"read README"}}}
{"event":"rpc_response","timestamp":"2026-04-12T10:00:00.050Z","session_id":"sess_123","payload":{"request_id":"1","command":"prompt","result":{"reply":"read README"}}}
```

示例输入：

```json
{"id":"1","type":"prompt","prompt":"read README"}
{"id":"2","type":"summary"}
```

## 5. 测试

```bash
pytest --rootdir="D:/develop/agent/ui-mono" "D:/develop/agent/ui-mono/tests"
```

当前测试覆盖：

- 工具读写与路径越界保护
- surrogate 输入清洗
- tool_error 事件记录与回填
- session snapshot 恢复
- branch relationship
- demo 命令输出
- demo / inspect-session 的 JSON 与 JSON stream 输出
- session 浏览命令的 JSON / JSON stream 输出
- inspect/session/tree 类 payload 结构对齐

## 设计取舍

参考 pi-mono，但当前仍保持单包 Python MVP，不照搬 monorepo：

- **照搬的思想**
  - runtime 独立于 provider
  - 会话事件流而不是单纯 history list
  - branch / resume / compaction 是一等能力
  - 失败路径也要可观察
  - inspect 和 JSON 输出优先面向“可验证”，而不是先做复杂 UI

- **暂不照搬的部分**
  - 多包 monorepo
  - TUI / Web UI
  - RPC / JSON streaming 模式的完整协议层
  - 扩展系统与复杂 settings 层

这样做的目标不是功能堆叠，而是先把最关键的运行时抽象和验证闭环补扎实。

## 为什么这样设计

这部分是最适合在简历或面试里复述的设计动机。

### 1. 为什么要把 runtime 单独抽出来

如果把模型调用、工具执行、session 写入、摘要压缩都揉在 CLI 或一个简单 while loop 里，代码虽然能跑，但后续很难验证每一轮到底发生了什么。

把 `AgentSessionRuntime` 单独抽出来后，一次 turn 的职责变得明确：

- 组装上下文
- 调用模型
- 执行工具
- 记录事件
- 触发 compaction
- 返回可恢复状态

这样做的价值是：**把“能聊天”提升成“能被验证、能恢复、能演进的运行时”**。

### 2. 为什么 session 要存成事件流，而不是只存 history

只存最终 history 虽然简单，但会丢掉很多关键过程：

- 哪一步触发了工具调用
- 哪次工具失败了
- 什么时候发生了 compaction
- 当前 branch 是从哪里分出来的

所以 `ui-mono` 采用 JSONL 事件流，把 `tool_call`、`tool_result`、`tool_error`、`branch`、`compaction` 都保留下来。

这样做的价值是：**session 不再只是聊天记录，而是可重放、可检查、可分叉的运行轨迹**。

### 3. 为什么 compaction 要做成显式事件

上下文窗口有限，长对话不可能永远把全部历史原样塞给模型。简单截断虽然省事，但模型会失去之前的重要上下文。

因此这里没有只做“裁掉前面消息”，而是把 compaction 做成显式事件：

- 保留尾部 history
- 为被压缩部分生成 summary
- 在恢复时重新注入 summary 与剩余上下文

这样做的价值是：**把“丢上下文”变成“有边界、有记录的上下文压缩”**。

### 4. 为什么先做 inspect / JSON 输出，而不是先做界面

参考 pi-mono 的思路，真正重要的不是先做一个漂亮前端，而是先保证 runtime 的行为可观察。

所以当前优先补的是：

- `inspect-session`：验证 resume / branch / compaction
- `--json` 输出：把运行结果变成结构化汇总对象，并逐步贴近 runtime payload 结构
- `--json-stream` 输出：逐条输出统一 runtime 事件 schema（`event` / `timestamp` / `session_id` / `payload`）
- `sessions-list` / `sessions-summary` / `sessions-tree`：把 session 浏览能力补齐
- runtime observer / dispatcher：把运行时事件发送与 CLI 输出解耦
- provider 真流式输出：让 `message_update.delta` 变成真实增量，并把完整文本放到 `message_end.content`，避免每次 update 都重复整段内容

这样做的价值是：**先把系统做成可调试、可验证、可解释，再考虑更重的交互层**。

### 6. 为什么要区分 chat / run / rpc

三者不是三套不同 agent，而是同一个 runtime 的三个入口：

- `chat`：给人类交互使用
- `run`：给脚本 / CI 的一次性 headless 模式
- `rpc`：给程序集成的长连接 JSONL 模式

这样做的价值是：**同一套 session、stream、observer、tool calling 逻辑，可以同时服务人类交互和程序调用。**

这两个东西看起来都像“事件”，但职责不同。

- **runtime JSON stream**：服务运行期观察，强调前端、RPC、TUI、脚本集成时“当前发生了什么”
- **session event log**：服务持久化恢复，强调之后还能不能把 session 正确读回来、继续跑下去

所以现在 `ui-mono` 把它们分开：

- runtime stream 统一为 `event / timestamp / session_id / payload`
- session log 继续使用针对恢复友好的 JSONL 事件模型

这样做的价值是：**把“运行时可观察性”和“状态持久化”拆成两套边界清晰的机制，后续接 RPC / TUI / Web UI 时不会和 session 恢复语义混在一起。**
