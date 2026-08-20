# Nano-dsh 读者指南

nano-dsh 是一个小型、同步的教学 harness。它展示了一个 CLI 任务如何经过动态 Plugin、真实 Tool 和 DeepSeek Model Step，成为一次 Agent Run。

## 1. 一次完整的 Agent Run

正常的 headless run 从这个命令开始：

```text
nano-dsh "Fix the selected workspace" --workspace "$PWD/../nano-dsh-workspace" --api-key-file "$PWD/.key"
```

这是端到端执行链。它是理解这个仓库最有用的心智模型。

```mermaid
sequenceDiagram
    participant CLI as CLI
    participant Boot as Profile and Loader
    participant Runtime as Context and Fibers
    participant Agent as AgentLoop
    participant Model as DeepSeek
    participant Tools as Editor and Bash

    CLI->>Boot: CommandLineArgs(task, workspace, api-key-file)
    Boot->>Runtime: load Profile, Bundles, and Plugin Fibers
    Runtime->>Agent: activate AgentLoop and register AgentFactory
    Runtime->>Agent: Headless Runner calls agents.create(workspace)
    Agent->>Model: Model Step 1 with Session Events and Tool definitions
    Model->>Tools: Tool Calls for editor and bash
    Tools->>Agent: Tool Results become Session Events
    Agent->>Model: later Model Step with prior Tool Results
    Model->>CLI: final assistant response
    CLI->>Runtime: dispose Fibers in reverse order
```

下面用具体代码位置重述同一条执行链。

1. CLI 在 [nano_dsh/__main__.py](nano_dsh/__main__.py) 中解析 `task`、`--workspace` 和 `--api-key-file`。它解析路径，并创建 `CommandLineArgs`。
2. `main()` 将 `cmdline_args` 作为 root Service 传给 [nano_dsh/boot.py](nano_dsh/boot.py)。它选择 [profiles/headless.toml](profiles/headless.toml)。
3. Profile 列出 [bundles/base.toml](bundles/base.toml) 和 [bundles/headless.toml](bundles/headless.toml)。[nano_dsh/loader.py](nano_dsh/loader.py) 按这个顺序读取它们，并导入每个 Plugin 模块。
4. Context 为每个 Plugin 创建一个 Fiber。每个 Fiber 先输出 `PENDING`。只有所需的每个 Service 都可用时，Fiber 才变为 `ACTIVE`。正常顺序是 `sessions`、`agents`、`tools`、`bash`、`editor`、`deepseek`、`agent_loop`、`headless_startup` 和 `headless_runner`。
5. `deepseek` 读取单行 key 文件，并提供 `llm`。当 `sessions`、`agents`、`tools` 和 `llm` 都存在时，[nano_dsh/plugins/agent_loop.py](nano_dsh/plugins/agent_loop.py) 激活。它注册一个 `AgentFactory`；此时还不会创建 Agent。
6. [nano_dsh/plugins/headless_runner.py](nano_dsh/plugins/headless_runner.py) 是 Driver。它先用 `llm.system_prompt` 和 User Task 开始 Execution Trace。然后调用 `agents.create(workspace).run(task)`。Factory 创建一个新的内存内 Session。
7. Agent 追加一个用户 Session Event，并通过 [nano_dsh/plugins/deepseek.py](nano_dsh/plugins/deepseek.py) 发送 Model Step 1。模型可以返回 `str_replace_editor` 和 `bash` 的 Tool Call。
8. [nano_dsh/plugins/editor.py](nano_dsh/plugins/editor.py) 或 [nano_dsh/plugins/bash.py](nano_dsh/plugins/bash.py) 执行每个调用。可预期拒绝返回 `ToolOutput(content, failed=True)`。`ToolsService` 将它记录为 failed，并通过 `ToolResultEvent` 把 content 返回模型。
9. 循环会发送后续的 Model Step。它包含先前的 assistant event 和 Tool Result。它在一个 Model Step 没有 Tool Call 时停止。它要求并返回 non-empty final content。
10. `boot()` 成功后，`main()` 调用 `context.dispose()`。正常 cleanup 按反向顺序访问 Fiber 和 Effect。意外的 Boot、Plugin、cleanup、JSON、network、filesystem、encoding 或 subprocess timeout 错误会直接传播，并保留 Python 原始堆栈。

Execution Trace 从 System Prompt 开始。然后打印 User Task、Reasoning Content、assistant content、Tool Call、Tool Result 和 runtime event。tracing layer 不记录 Provider API key 或 HTTP header。Tool output 会原样打印。

## 2. 最少术语

| 术语 | 在 nano-dsh 中的含义 |
| --- | --- |
| Profile | 选择有序 Bundle 列表的 TOML 文件。headless Profile 是 [profiles/headless.toml](profiles/headless.toml)。 |
| Bundle | 一个有序的 Plugin Specification TOML 组。它决定 Fiber 创建顺序，而不决定激活顺序。 |
| Plugin | 一个可加载能力。它的 `apply(ctx, config)` 函数可以提供 Service 或注册 Effect。 |
| Fiber | 一个已应用的 Plugin 实例。它有生命周期状态，并拥有其加载期间创建的 Effect。 |
| Service | Context 中的一个具名能力。Plugin 依赖 Service 名称，而不是具体 Plugin 身份。 |
| Effect | 由 Fiber 拥有的 setup action，以及可选的 disposer。正常 disposal 按注册的反向顺序运行 disposer。 |
| Session Event | 一个有类型的内存内记录。它可以是用户输入、assistant 输出或 Tool Result。 |
| Provider | 提供一个 Service 的 Plugin。DeepSeek Provider 提供 `llm`。 |
| Tool Call | 模型发出的请求。它有 Tool 名称和 JSON 参数。它会成为 Tool Execution，再成为 Tool Result。 |

## 3. 按五层阅读代码

一次只读一层。每层回答不同的问题。

### 1. Apps

- 文件：[nano_dsh/__main__.py](nano_dsh/__main__.py)、[nano_dsh/plugins/headless_startup.py](nano_dsh/plugins/headless_startup.py) 和 [nano_dsh/plugins/headless_runner.py](nano_dsh/plugins/headless_runner.py)。
- 输入：命令行任务、Workspace 路径和 API-key-file 路径。
- 输出：标准输出中的 final assistant text，以及标准错误中的完整 Execution Trace。
- 为什么存在：这一层验证面向用户的输入，并启动恰好一次 headless Agent Run。Runner 是 Driver。只有组装过程提供了它需要的 Service 后，它才启动 Agent。

### 2. Boot 和 Bundle 组装

- 文件：[nano_dsh/boot.py](nano_dsh/boot.py)、[nano_dsh/loader.py](nano_dsh/loader.py)、[profiles/headless.toml](profiles/headless.toml)、[bundles/base.toml](bundles/base.toml) 和 [bundles/headless.toml](bundles/headless.toml)。
- 输入：root Service 和被选中的 Profile。
- 输出：一个已组装的 Context。所有启用的 Fiber 都是 `ACTIVE`。未解析的 Fiber 会触发内部 `assert`。
- 为什么存在：它让应用组装是声明式的。它也展示 Bundle 给出创建顺序，而 Service 可用性给出激活顺序。

### 3. Cordis runtime

- 文件：[nano_dsh/cordis.py](nano_dsh/cordis.py) 和 [nano_dsh/contracts.py](nano_dsh/contracts.py)。
- 输入：Plugin Specification、所需 Service 名称和 Plugin `apply` 函数。
- 输出：active Fiber、已发布的 Service 和归 Fiber 所有的清理动作。
- 为什么存在：这是最小的动态生命周期。Consumer 可以保持 `PENDING`，在 Provider 到来时激活，在该 Service 消失时回到 `PENDING`，并在它返回时重新激活。正常 cleanup 按注册的反向顺序运行 disposer。

### 4. Agent core

- 文件：[nano_dsh/plugins/agents.py](nano_dsh/plugins/agents.py)、[nano_dsh/plugins/sessions.py](nano_dsh/plugins/sessions.py)、[nano_dsh/plugins/tools.py](nano_dsh/plugins/tools.py)、[nano_dsh/plugins/agent_loop.py](nano_dsh/plugins/agent_loop.py)、[nano_dsh/plugins/bash.py](nano_dsh/plugins/bash.py) 和 [nano_dsh/plugins/editor.py](nano_dsh/plugins/editor.py)。
- 输入：任务、Workspace、`llm` Service 和已注册的 Tool definition。
- 输出：一个 append-only Session，以及第一个没有 Tool Call 的 Model Step 的 non-empty content。带 Tool Call 的 Model Step 可以有 null content。可预期 Tool 拒绝返回 `ToolOutput(content, failed=True)`。
- 为什么存在：这一层让 AgentFactory 注册与 Agent 创建分离。它也让顺序 Tool 执行和 Session state 独立于 Provider wire format。

### 5. Provider

- 文件：[nano_dsh/plugins/deepseek.py](nano_dsh/plugins/deepseek.py)。
- 输入：Session Event、Tool definition 和单行 API key。
- 输出：归一化的 assistant output。它包含 final content、可选的 Reasoning Content 和零个或多个 Tool Call。
- 为什么存在：这是 Agent core 与 DeepSeek Chat Completions protocol 之间的边界。它跨含 Tool 的 Model Step 保留 Reasoning Content，但不让 core 依赖 protocol message。

## 4. 快速开始

要求：Python 3.12 和一个 DeepSeek API key。生产代码除了 Python 标准库外没有运行时依赖。

在仓库根目录中，创建隔离 Python 环境，并安装本地命令：

```bash
python3.12 --version
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

创建 `.key`，内容必须恰好是一行非空文本。该行是 API key。不要加引号或额外行。

```bash
printf '%s\n' 'your-api-key-goes-here' > .key
```

创建一个可丢弃的 Workspace。把它视为可信本地 coding Agent 可以写入的位置。

```bash
mkdir -p "$PWD/../nano-dsh-workspace"
nano-dsh "Inspect the Workspace and describe its files." --workspace "$PWD/../nano-dsh-workspace" --api-key-file "$PWD/.key"
```

CLI 自己选择 headless Profile。你不传入 Profile 参数。`--workspace` 必须是一个已存在的目录。默认 Workspace 是当前目录。默认 API-key file 是当前目录中的 `.key`。

## 5. 测试

仓库已包含 Live Acceptance Suite。它使用三个可丢弃的 Bug Fixture：一个 logic error、一个 boundary error 和一个 missing implementation。要满足验收要求，每次 run 都必须使用真实 DeepSeek API，同时调用 `str_replace_editor` 和 `bash`，把 Tool Result 返回给后续 Model Step，通过 fixture 的 `unittest` suite，并以 final assistant text 结束。

运行命令：

```bash
python examples/example.py --api-key-file .key
```

一个成功场景从下面的内容开始：

```text
=== SYSTEM ===
You are a coding agent. ...
=== USER ===
Correct the inventory availability calculation. ...
=== REASONING ===
...
=== TOOL CALL ===
...
=== TOOL RESULT ===
...
=== ASSISTANT ===
...
logic-bug: PASS
```

三个 fixture 都会重复这个序列。最后一行是 `Summary: 3/3 PASS`。通过 `tee` 保存标准输出，就能得到完整轨迹：

```bash
python examples/example.py --api-key-file .key | tee example-output.log
```

脚本对每个 fixture 只执行一次。它不会自动 retry。

## 引用

如果这个仓库对你的工作有帮助，请使用以下 BibTeX 引用：

```bibtex
@misc{mu2026nanodsh,
  author       = {Guohong Mu},
  title        = {nano-dsh: A Minimal Python Reconstruction of DeepSeek Harness},
  year         = {2026},
  howpublished = {\url{https://github.com/mgh233/nano-dsh}},
}
```
