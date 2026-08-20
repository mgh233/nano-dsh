# nano-dsh Reader Guide

nano-dsh is a small, synchronous teaching harness that shows how a CLI task becomes an Agent Run through dynamic Plugins, real Tools, and a DeepSeek Model Step.

Read this guide once from top to bottom. Then follow the five-layer order when you read the code.

## 0. Original Harness and the teaching path

This table names the direct teaching path. nano-dsh keeps the visible control flow and omits production machinery that does not help explain it.

| Layer | Original DeepSeek Harness | nano-dsh teaching path |
| --- | --- | --- |
| Apps | Production CLI and application surfaces. | One headless CLI Driver. No Web UI or session persistence. |
| Boot / Profile / Loader | Production Profile composition and Loader machinery. | Ordered TOML Profile and Bundles load Plugin modules directly. No Profile Patch overlays or hot reload. |
| Cordis | Dynamic Plugin runtime with production scope and asynchronous lifecycle machinery. | One synchronous Context with Fibers, Services, Effects, pending Consumers, removal, and reactivation. No scopes, async lifecycle, or transactional rollback. |
| Agent core | Production Agent, Session, and Tool composition. | One AgentFactory, one in-memory Session, and sequential Tool Calls. No multi-Agent execution, Skills, Memory, or Workspace-instruction loading. |
| DeepSeek Provider / tools | Production provider and Tool integrations. | One non-streaming Chat Completions Provider plus Bash and Editor. No retries, streaming, persistent shell, or operating-system sandbox. |
| Failure flow | Production layers translate and recover from selected errors. | The teaching code has no explicit `raise`, `try`, or `except` statements. Internal contracts use `assert`. Expected Tool failures use `ToolOutput`. Other errors keep their native Python traceback. |

## 1. One complete Agent Run

The normal headless run starts from this command:

```text
nano-dsh "Fix the selected workspace" --workspace "$PWD/../nano-dsh-workspace" --api-key-file "$PWD/.key"
```

This is the end-to-end trace. It is the most useful mental model for the repository.

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

Here is the same trace with concrete code locations.

1. The CLI parses `task`, `--workspace`, and `--api-key-file` in [nano_dsh/__main__.py](nano_dsh/__main__.py). It resolves the paths and creates `CommandLineArgs`.
2. `main()` passes `cmdline_args` as a root Service to [nano_dsh/boot.py](nano_dsh/boot.py). It selects [profiles/headless.toml](profiles/headless.toml).
3. The Profile lists [bundles/base.toml](bundles/base.toml) and [bundles/headless.toml](bundles/headless.toml). [nano_dsh/loader.py](nano_dsh/loader.py) reads them in that order and imports each Plugin module.
4. The Context creates one Fiber per Plugin. Each Fiber first emits `PENDING`. A Fiber becomes `ACTIVE` only after every required Service is available. The normal order is `sessions`, `agents`, `tools`, `bash`, `editor`, `deepseek`, `agent_loop`, `headless_startup`, and `headless_runner`.
5. `deepseek` reads the one-line key file and provides `llm`. Once `sessions`, `agents`, `tools`, and `llm` exist, [nano_dsh/plugins/agent_loop.py](nano_dsh/plugins/agent_loop.py) activates. It registers an `AgentFactory`; it does not yet create an Agent.
6. [nano_dsh/plugins/headless_runner.py](nano_dsh/plugins/headless_runner.py) is the Driver. It calls `agents.create(workspace).run(task)`. The factory creates a new in-memory Session.
7. The Agent appends a user Session Event and sends Model Step 1 through [nano_dsh/plugins/deepseek.py](nano_dsh/plugins/deepseek.py). The model can return Tool Calls for `str_replace_editor` and `bash`.
8. [nano_dsh/plugins/editor.py](nano_dsh/plugins/editor.py) or [nano_dsh/plugins/bash.py](nano_dsh/plugins/bash.py) executes each call. A predictable rejection returns `ToolOutput(content, failed=True)`. `ToolsService` traces it as failed and returns its content to the model through a `ToolResultEvent`.
9. The loop sends a later Model Step with the earlier assistant event and Tool Results. It stops when a Model Step has no Tool Calls. It requires and returns non-empty final content.
10. After `boot()` succeeds, `main()` calls `context.dispose()`. Normal cleanup visits Fibers and Effects in reverse order. An unexpected Boot, Plugin, cleanup, JSON, network, filesystem, encoding, or subprocess timeout error propagates directly with its native Python traceback.

The trace is concise by design. It does not print the API key or Reasoning Content.

## 2. Minimal vocabulary

Use these definitions while reading. [CONTEXT.md](CONTEXT.md) is the canonical glossary.

| Term | Meaning in nano-dsh |
| --- | --- |
| Profile | A TOML file that selects an ordered list of Bundles. The headless Profile is [profiles/headless.toml](profiles/headless.toml). |
| Bundle | An ordered TOML group of Plugin Specifications. It determines Fiber creation order, not activation order. |
| Plugin | A loadable capability. Its `apply(ctx, config)` function can provide Services or register Effects. |
| Fiber | One applied Plugin instance. It has a lifecycle state and owns the Effects created while it loads. |
| Service | A named capability in the Context. A Plugin requires Service names, not concrete Plugin identities. |
| Effect | A Fiber-owned setup action and optional disposer. Normal disposal runs disposers in reverse registration order. |
| Session Event | One typed in-memory record of user input, assistant output, or a Tool Result. |
| Provider | A Plugin that supplies a Service. The DeepSeek Provider supplies `llm`. |
| Tool Call | A model request with a Tool name and JSON arguments. It becomes a Tool Execution, then a Tool Result. |

Do not merge these concepts. A Fiber becoming active is not an Agent Run. Registering an AgentFactory is not creating an Agent. A failed Tool Output is still a model-visible Tool Result.

## 3. Read the code in five layers

Read one layer at a time. Each layer answers a different question.

### 1. Apps

- Files: [nano_dsh/__main__.py](nano_dsh/__main__.py), [nano_dsh/plugins/headless_startup.py](nano_dsh/plugins/headless_startup.py), and [nano_dsh/plugins/headless_runner.py](nano_dsh/plugins/headless_runner.py).
- Input: command-line task, Workspace path, and API-key-file path.
- Output: final assistant text on standard output and a concise Execution Trace on standard error.
- Why it exists: this layer validates user-facing input and starts exactly one headless Agent Run. The Runner is a Driver. It starts the Agent only after assembly supplies its required Services.

### 2. Boot and Bundle composition

- Files: [nano_dsh/boot.py](nano_dsh/boot.py), [nano_dsh/loader.py](nano_dsh/loader.py), [profiles/headless.toml](profiles/headless.toml), [bundles/base.toml](bundles/base.toml), and [bundles/headless.toml](bundles/headless.toml).
- Input: root Services and the selected Profile.
- Output: an assembled Context in which every enabled Fiber is `ACTIVE`. An unresolved Fiber fails an internal `assert`.
- Why it exists: it makes application composition declarative. It also shows that a Bundle gives creation order while Service availability gives activation order.

### 3. Cordis runtime

- Files: [nano_dsh/cordis.py](nano_dsh/cordis.py) and [nano_dsh/contracts.py](nano_dsh/contracts.py).
- Input: Plugin Specifications, required Service names, and Plugin `apply` functions.
- Output: active Fibers, published Services, and Fiber-owned cleanup.
- Why it exists: this is the minimal dynamic lifecycle. A Consumer can remain `PENDING`, activate when a Provider arrives, return to `PENDING` if that Service disappears, and reactivate when it returns. Normal cleanup runs disposers in reverse registration order.

### 4. Agent core

- Files: [nano_dsh/plugins/agents.py](nano_dsh/plugins/agents.py), [nano_dsh/plugins/sessions.py](nano_dsh/plugins/sessions.py), [nano_dsh/plugins/tools.py](nano_dsh/plugins/tools.py), [nano_dsh/plugins/agent_loop.py](nano_dsh/plugins/agent_loop.py), [nano_dsh/plugins/bash.py](nano_dsh/plugins/bash.py), and [nano_dsh/plugins/editor.py](nano_dsh/plugins/editor.py).
- Input: a task, a Workspace, an `llm` Service, and registered Tool definitions.
- Output: an append-only Session and the non-empty content of the first Model Step without Tool Calls. A Model Step with Tool Calls can have null content. Predictable Tool rejections return `ToolOutput(content, failed=True)`.
- Why it exists: this layer keeps AgentFactory registration separate from Agent creation. It also keeps sequential Tool execution and Session state independent from the provider wire format.

### 5. Provider

- File: [nano_dsh/plugins/deepseek.py](nano_dsh/plugins/deepseek.py).
- Input: Session Events, Tool definitions, and the one-line API key.
- Output: normalized assistant output with final content, optional Reasoning Content, and zero or more Tool Calls.
- Why it exists: this is the boundary between the Agent core and the DeepSeek Chat Completions protocol. It preserves Reasoning Content across Tool-using Model Steps without making the core depend on protocol messages.

After this pass, read the offline integration test in [tests/test_headless_app.py](tests/test_headless_app.py). It uses a scripted transport to show the same lifecycle without a network request.

## 4. Quick start

Requirements: Python 3.12 and a DeepSeek API key. Production code has no runtime dependencies beyond the Python standard library.

From the repository root, create an isolated Python environment and install the local command:

```bash
python3.12 --version
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Create `.key` with exactly one non-empty line. The line is the API key. Do not add quotes or extra lines.

```bash
printf '%s\n' 'your-api-key-goes-here' > .key
```

Create a disposable Workspace. Treat it as writable by a trusted local coding Agent.

```bash
mkdir -p "$PWD/../nano-dsh-workspace"
nano-dsh "Inspect the Workspace and describe its files." --workspace "$PWD/../nano-dsh-workspace" --api-key-file "$PWD/.key"
```

The CLI selects the headless Profile itself. You do not pass a Profile argument. `--workspace` must name an existing directory. The default Workspace is the current directory. The default API-key file is `.key` in the current directory.

## 5. Test in two ways

### Full offline unit test suite

Run this without an API key or network access:

```bash
python -m unittest discover -v
```

This suite verifies the Fiber lifecycle, dynamic loading, reverse Effect cleanup, Session serialization, Reasoning Content round-trip, ordered Tool Calls, Editor confinement, Bash behavior, and a full scripted headless Agent Run.

### Three-fixture Live Acceptance Suite

The included Live Acceptance Suite uses three disposable Bug Fixtures: one logic error, one boundary error, and one missing implementation. For acceptance, each run must use the real DeepSeek API, call both `str_replace_editor` and `bash`, return Tool Results to a later Model Step, pass the fixture's `unittest` suite, and finish with final assistant text.

Run it with:

```bash
python examples/example.py --api-key-file .key
```

A successful run prints:

```text
logic-bug: PASS
boundary-bug: PASS
missing-implementation: PASS
Summary: 3/3 PASS
```

The script performs one attempt per fixture. It does not retry automatically.

Verification record (2026-08-20): this revision passed the offline suite 83/83 and the real-API Live Acceptance suite 3/3. Production Python contains 761 non-empty, non-comment lines. The largest production file contains 140 such lines. The repository contains 34 Python files with zero AST `Raise`, `Try`, and `TryStar` nodes.

## 6. Security boundary and failure behavior

- Bash is a trusted local capability. It starts in the selected Workspace, but it is not an operating-system sandbox. It can access normal host resources available to the process.
- Every Bash Tool Execution starts a fresh `/bin/bash` process. Shell state does not persist. It has a 300-second timeout and a 16,000-character model-visible output limit.
- `str_replace_editor` accepts only absolute paths. It resolves paths and rejects targets outside the Workspace, including symbolic-link escapes. This path confinement does not sandbox Bash.
- `.key` is ignored by Git. The Provider reads one non-empty line into memory. The Bash child environment removes `DEEPSEEK_API_KEY`.
- There is no automatic retry for provider requests or the live suite. There is no Model Step cap.
- Internal invariants use concise `assert` statements. Examples include unique Service Providers, one AgentFactory, the DeepSeek response shape, and non-empty final assistant content.
- Predictable Tool failures return `ToolOutput(content, failed=True)`. Examples include an unknown Tool, a nonzero Bash exit, and a rejected Editor operation. `ToolsService` writes the content back to the model and records a failed trace.
- JSON, network, filesystem, encoding, and subprocess timeout errors are not wrapped. Python exposes the original traceback.

Use a disposable Workspace for live runs. Do not put secrets or important host files where a trusted Bash process can reach them.

## 7. Deliberately not implemented

nano-dsh keeps the teaching path small. It intentionally excludes:

- Web UI and session persistence.
- Scope isolation and multi-Agent execution.
- Streaming responses and asynchronous execution.
- Profile Patch overlays and configuration hot reload.
- Transactional rollback.
- Persistent Bash, PTY support, and background jobs.
- An operating-system sandbox.
- Automatic API retries and a Model Step limit.
- Skills, Memory, and Workspace instruction loading.

These omissions are part of the design. They keep the complete execution chain readable without claiming production-harness coverage.

## 8. Collaborate through branches and worktrees

Use one assigned change per independent worktree. Commit that change with a Conventional Commit. An independent read-only reviewer checks the branch. Fix actionable findings on the same branch. Run the branch tests. Then merge to `main` with `--no-ff` and run the main tests again. Do not squash the branch.

This workflow preserves a reviewable implementation history without making workers edit the same worktree.

## 9. Continue with the canonical documents

[CONTEXT.md](CONTEXT.md) is the canonical terminology and runtime glossary. Read it when a term in this guide is still unclear.

[PLAN.md](PLAN.md) states the product boundary, runtime contracts, verification target, and collaboration gate.

[docs/adr/](docs/adr/) records the hard-to-reverse choices: semantic fidelity, the dynamic Plugin lifecycle, trusted Bash, Session/Provider separation, deferred Agent creation, the code-size cap, synchronous execution, Python 3.12 with no runtime dependencies, and failed `ToolOutput` semantics.
