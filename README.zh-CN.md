# nano-dsh 读者指南

nano-dsh 是一个小型、同步的教学 harness。它展示了一个 CLI 任务如何经过动态 Plugin、真实 Tool 和 DeepSeek Model Step，成为一次 Agent Run。

先从头到尾读一遍本指南。之后按五层顺序阅读代码。

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

1. CLI 在 [src/nano_dsh/__main__.py](src/nano_dsh/__main__.py) 中解析 `task`、`--workspace` 和 `--api-key-file`。它解析路径，并创建 `CommandLineArgs`。
2. `main()` 将 `cmdline_args` 作为 root Service 传给 [src/nano_dsh/boot.py](src/nano_dsh/boot.py)。它选择 [profiles/headless.toml](profiles/headless.toml)。
3. Profile 列出 [bundles/base.toml](bundles/base.toml) 和 [bundles/headless.toml](bundles/headless.toml)。[src/nano_dsh/loader.py](src/nano_dsh/loader.py) 按这个顺序读取它们，并导入每个 Plugin 模块。
4. Context 为每个 Plugin 创建一个 Fiber。每个 Fiber 先输出 `PENDING`。只有所需的每个 Service 都可用时，Fiber 才变为 `ACTIVE`。正常顺序是 `sessions`、`agents`、`tools`、`bash`、`editor`、`deepseek`、`agent_loop`、`headless_startup` 和 `headless_runner`。
5. `deepseek` 读取单行 key 文件，并提供 `llm`。当 `sessions`、`agents`、`tools` 和 `llm` 都存在时，[src/nano_dsh/plugins/agent_loop.py](src/nano_dsh/plugins/agent_loop.py) 激活。它注册一个 `AgentFactory`；此时还不会创建 Agent。
6. [src/nano_dsh/plugins/headless_runner.py](src/nano_dsh/plugins/headless_runner.py) 是 Driver。它调用 `agents.create(workspace).run(task)`。Factory 创建一个新的内存内 Session。
7. Agent 追加一个用户 Session Event，并通过 [src/nano_dsh/plugins/deepseek.py](src/nano_dsh/plugins/deepseek.py) 发送 Model Step 1。模型可以返回 `str_replace_editor` 和 `bash` 的 Tool Call。
8. [src/nano_dsh/plugins/editor.py](src/nano_dsh/plugins/editor.py) 或 [src/nano_dsh/plugins/bash.py](src/nano_dsh/plugins/bash.py) 执行每个调用。[src/nano_dsh/plugins/tools.py](src/nano_dsh/plugins/tools.py) 将预期的 Tool Failure 转换成模型可见的 Tool Result。Agent 将每个结果追加为 `ToolResultEvent`。
9. 循环会发送后续的 Model Step。它包含先前的 assistant event 和 Tool Result。循环持续到 Provider 返回非空的 final text。该文本写到标准输出。
10. `main()` 总会调用 `context.dispose()`。Fiber 按创建顺序的反向清理。它们的 Effect 会移除 AgentFactory、Tool 注册和归 Fiber 所有的 Service。

这条 trace 有意保持简洁。它不会打印 API key 或 Reasoning Content。

## 2. 最少术语

阅读时使用这些定义。[CONTEXT.md](CONTEXT.md) 是规范术语表。

| 术语 | 在 nano-dsh 中的含义 |
| --- | --- |
| Profile | 选择有序 Bundle 列表的 TOML 文件。headless Profile 是 [profiles/headless.toml](profiles/headless.toml)。 |
| Bundle | 一个有序的 Plugin Specification TOML 组。它决定 Fiber 创建顺序，而不决定激活顺序。 |
| Plugin | 一个可加载能力。它的 `apply(ctx, config)` 函数可以提供 Service 或注册 Effect。 |
| Fiber | 一个已应用的 Plugin 实例。它有生命周期状态，并拥有其加载期间创建的 Effect。 |
| Service | Context 中的一个具名能力。Plugin 依赖 Service 名称，而不是具体 Plugin 身份。 |
| Effect | 由 Fiber 拥有的 setup action，以及可选的 disposer。清理按注册的反向顺序进行。 |
| Session Event | 一个有类型的内存内记录。它可以是用户输入、assistant 输出或 Tool Result。 |
| Provider | 提供一个 Service 的 Plugin。DeepSeek Provider 提供 `llm`。 |
| Tool Call | 模型发出的请求。它有 Tool 名称和 JSON 参数。它会成为 Tool Execution，再成为 Tool Result。 |

不要合并这些概念。Fiber 变为 active 不等于 Agent Run。注册 AgentFactory 不等于创建 Agent。Tool Failure 不等于 Run Failure。

## 3. 按五层阅读代码

一次只读一层。每层回答不同的问题。

### 1. Apps

- 文件：[src/nano_dsh/__main__.py](src/nano_dsh/__main__.py)、[src/nano_dsh/plugins/headless_startup.py](src/nano_dsh/plugins/headless_startup.py) 和 [src/nano_dsh/plugins/headless_runner.py](src/nano_dsh/plugins/headless_runner.py)。
- 输入：命令行任务、Workspace 路径和 API-key-file 路径。
- 输出：标准输出中的 final assistant text，以及标准错误中的简洁 Execution Trace。
- 为什么存在：这一层验证面向用户的输入，并启动恰好一次 headless Agent Run。Runner 是 Driver。只有组装过程提供了它需要的 Service 后，它才启动 Agent。

### 2. Boot 和 Bundle 组装

- 文件：[src/nano_dsh/boot.py](src/nano_dsh/boot.py)、[src/nano_dsh/loader.py](src/nano_dsh/loader.py)、[profiles/headless.toml](profiles/headless.toml)、[bundles/base.toml](bundles/base.toml) 和 [bundles/headless.toml](bundles/headless.toml)。
- 输入：root Service 和被选中的 Profile。
- 输出：一个已组装的 Context。所有启用的 Fiber 都是 `ACTIVE`；否则会得到可见的 `RunFailure`。
- 为什么存在：它让应用组装是声明式的。它也展示 Bundle 给出创建顺序，而 Service 可用性给出激活顺序。

### 3. Cordis runtime

- 文件：[src/nano_dsh/cordis.py](src/nano_dsh/cordis.py) 和 [src/nano_dsh/contracts.py](src/nano_dsh/contracts.py)。
- 输入：Plugin Specification、所需 Service 名称和 Plugin `apply` 函数。
- 输出：active Fiber、已发布的 Service 和归 Fiber 所有的清理动作。
- 为什么存在：这是最小的动态生命周期。Consumer 可以保持 `PENDING`，在 Provider 到来时激活，在该 Service 消失时回到 `PENDING`，并在它返回时重新激活。

### 4. Agent core

- 文件：[src/nano_dsh/plugins/agents.py](src/nano_dsh/plugins/agents.py)、[src/nano_dsh/plugins/sessions.py](src/nano_dsh/plugins/sessions.py)、[src/nano_dsh/plugins/tools.py](src/nano_dsh/plugins/tools.py)、[src/nano_dsh/plugins/agent_loop.py](src/nano_dsh/plugins/agent_loop.py)、[src/nano_dsh/plugins/bash.py](src/nano_dsh/plugins/bash.py) 和 [src/nano_dsh/plugins/editor.py](src/nano_dsh/plugins/editor.py)。
- 输入：任务、Workspace、`llm` Service 和已注册的 Tool definition。
- 输出：一个 append-only Session 和最终 assistant response。预期的 Tool Failure 会成为后续 Model Step 的 Tool Result。
- 为什么存在：这一层让 AgentFactory 注册与 Agent 创建分离。它也让顺序 Tool 执行和 Session state 独立于 Provider wire format。

### 5. Provider

- 文件：[src/nano_dsh/plugins/deepseek.py](src/nano_dsh/plugins/deepseek.py)。
- 输入：Session Event、Tool definition 和单行 API key。
- 输出：归一化的 assistant output。它包含 final content、可选的 Reasoning Content 和零个或多个 Tool Call。
- 为什么存在：这是 Agent core 与 DeepSeek Chat Completions protocol 之间的边界。它跨含 Tool 的 Model Step 保留 Reasoning Content，但不让 core 依赖 protocol message。

完成这一轮后，请读离线集成测试 [tests/test_headless_app.py](tests/test_headless_app.py)。它使用 scripted transport，在没有网络请求时展示同一个生命周期。

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

## 5. 用两种方式测试

### 完整离线 unit test suite

无需 API key 或网络访问，运行：

```bash
python -m unittest discover -s tests
```

这个 suite 验证 Fiber lifecycle、动态加载、反向 Effect cleanup、Session serialization、Reasoning Content round-trip、有序 Tool Call、Editor confinement、Bash behavior，以及完整的 scripted headless Agent Run。

### 三 fixture 的 Live Acceptance Suite

计划中的 Live Acceptance Suite 使用三个可丢弃的 Bug Fixture：一个 logic error、一个 boundary error 和一个 missing implementation。每次 run 都必须使用真实 DeepSeek API，同时调用 `str_replace_editor` 和 `bash`，把 Tool Result 返回给后续 Model Step，通过 fixture 的 `unittest` suite，并以 final assistant text 结束。

它的验收命令是：

```bash
python scripts/live_acceptance.py --api-key-file .key
```

当前 checkout 尚不包含 `fixtures/` 或 `scripts/live_acceptance.py`。该命令是 [PLAN.md](PLAN.md) 中规定的验收方法，不是已经完成或可在本地运行的结果。只有这些文件存在且命令成功退出后，才可以报告 live run 已通过。脚本不得自动 retry。

## 6. 安全边界和失败行为

- Bash 是 trusted local capability。它从所选 Workspace 启动，但不是 operating-system sandbox。它可以访问该进程通常可访问的 host resource。
- 每次 Bash Tool Execution 都启动一个新的 `/bin/bash` 进程。shell state 不会持久化。它有 300 秒 timeout，以及 16,000 字符的 model-visible output limit。
- `str_replace_editor` 只接受绝对路径。它会解析路径，并拒绝 Workspace 外的目标，包括 symbolic-link escape。这个路径限制不会 sandbox Bash。
- `.key` 被 Git 忽略。Provider 将一个非空行读入内存。Bash 子进程环境会移除 `DEEPSEEK_API_KEY`。
- Provider request 或计划中的 live suite 没有 automatic retry。没有 Model Step cap。Provider、configuration、Plugin 或 runtime invariant 失败会让 Agent Run 可见地结束。
- 预期的 Tool failure 不同。无效 Tool 参数、非零 Bash exit 或非唯一 editor replacement 会成为 Tool Result，Agent 可以在后续 Model Step 中检查它。

请为 live run 使用可丢弃的 Workspace。不要把 secret 或重要 host file 放在可信 Bash 进程可以访问的位置。

## 7. 刻意未实现的内容

nano-dsh 保持教学链足够小。它刻意不包含：

- Web UI 和 session persistence。
- Scope isolation 和 multi-Agent execution。
- Streaming response 和 asynchronous execution。
- Profile Patch overlay 和 configuration hot reload。
- Transactional rollback。
- Persistent Bash、PTY support 和 background job。
- Operating-system sandbox。
- Automatic API retry 和 Model Step limit。
- Skill、Memory 和 Workspace instruction loading。

这些省略是设计的一部分。它们让完整执行链可读，同时不声称覆盖 production harness。

## 8. 通过 branch 和 worktree 协作

在独立 worktree 中只做一个被分配的变更。用 Conventional Commit 提交这个变更。独立的只读 reviewer 检查 branch。在同一个 branch 上修复可操作的问题。运行 branch test。之后用 `--no-ff` 合并到 `main`，并再次运行 main test。不要 squash branch。

这个流程保留可审查的实现历史，同时避免多个 worker 修改同一个 worktree。

## 9. 继续阅读规范文档

[CONTEXT.md](CONTEXT.md) 是规范术语与 runtime glossary。当本指南中的术语仍不清楚时，请阅读它。

[PLAN.md](PLAN.md) 说明产品边界、runtime contract、verification target 和协作 gate。

[docs/adr/](docs/adr/) 记录难以逆转的选择：semantic fidelity、动态 Plugin lifecycle、trusted Bash、Session/Provider separation、延后 Agent creation、代码行数上限、synchronous execution、Python 3.12 无运行时依赖，以及 Tool Failure semantics。
