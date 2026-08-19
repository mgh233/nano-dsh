# nano-dsh Reader Guide

nano-dsh is a small, synchronous teaching harness that shows how a CLI task becomes an Agent Run through dynamic Plugins, real Tools, and a DeepSeek Model Step.

Read this guide once from top to bottom. Then follow the five-layer order when you read the code.

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

1. The CLI parses `task`, `--workspace`, and `--api-key-file` in [src/nano_dsh/__main__.py](src/nano_dsh/__main__.py). It resolves the paths and creates `CommandLineArgs`.
2. `main()` passes `cmdline_args` as a root Service to [src/nano_dsh/boot.py](src/nano_dsh/boot.py). It selects [profiles/headless.toml](profiles/headless.toml).
3. The Profile lists [bundles/base.toml](bundles/base.toml) and [bundles/headless.toml](bundles/headless.toml). [src/nano_dsh/loader.py](src/nano_dsh/loader.py) reads them in that order and imports each Plugin module.
4. The Context creates one Fiber per Plugin. Each Fiber first emits `PENDING`. A Fiber becomes `ACTIVE` only after every required Service is available. The normal order is `sessions`, `agents`, `tools`, `bash`, `editor`, `deepseek`, `agent_loop`, `headless_startup`, and `headless_runner`.
5. `deepseek` reads the one-line key file and provides `llm`. Once `sessions`, `agents`, `tools`, and `llm` exist, [src/nano_dsh/plugins/agent_loop.py](src/nano_dsh/plugins/agent_loop.py) activates. It registers an `AgentFactory`; it does not yet create an Agent.
6. [src/nano_dsh/plugins/headless_runner.py](src/nano_dsh/plugins/headless_runner.py) is the Driver. It calls `agents.create(workspace).run(task)`. The factory creates a new in-memory Session.
7. The Agent appends a user Session Event and sends Model Step 1 through [src/nano_dsh/plugins/deepseek.py](src/nano_dsh/plugins/deepseek.py). The model can return Tool Calls for `str_replace_editor` and `bash`.
8. [src/nano_dsh/plugins/editor.py](src/nano_dsh/plugins/editor.py) or [src/nano_dsh/plugins/bash.py](src/nano_dsh/plugins/bash.py) executes each call. [src/nano_dsh/plugins/tools.py](src/nano_dsh/plugins/tools.py) converts an expected Tool Failure into a model-visible Tool Result. The Agent appends each result as a `ToolResultEvent`.
9. The loop sends a later Model Step with the earlier assistant event and Tool Results. It repeats until the provider returns non-empty final text. That text goes to standard output.
10. After `boot()` succeeds, `main()` calls `context.dispose()` from its `finally` block. If Boot or Plugin activation fails, `boot()` itself disposes the Context and re-raises. In either cleanup path, Fibers clean up in reverse creation order. Their Effects remove the AgentFactory, Tool registrations, and Fiber-owned Services.

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
| Effect | A Fiber-owned setup action and optional disposer. Disposal runs in reverse registration order. |
| Session Event | One typed in-memory record of user input, assistant output, or a Tool Result. |
| Provider | A Plugin that supplies a Service. The DeepSeek Provider supplies `llm`. |
| Tool Call | A model request with a Tool name and JSON arguments. It becomes a Tool Execution, then a Tool Result. |

Do not merge these concepts. A Fiber becoming active is not an Agent Run. Registering an AgentFactory is not creating an Agent. A Tool Failure is not a Run Failure.

## 3. Read the code in five layers

Read one layer at a time. Each layer answers a different question.

### 1. Apps

- Files: [src/nano_dsh/__main__.py](src/nano_dsh/__main__.py), [src/nano_dsh/plugins/headless_startup.py](src/nano_dsh/plugins/headless_startup.py), and [src/nano_dsh/plugins/headless_runner.py](src/nano_dsh/plugins/headless_runner.py).
- Input: command-line task, Workspace path, and API-key-file path.
- Output: final assistant text on standard output and a concise Execution Trace on standard error.
- Why it exists: this layer validates user-facing input and starts exactly one headless Agent Run. The Runner is a Driver. It starts the Agent only after assembly supplies its required Services.

### 2. Boot and Bundle composition

- Files: [src/nano_dsh/boot.py](src/nano_dsh/boot.py), [src/nano_dsh/loader.py](src/nano_dsh/loader.py), [profiles/headless.toml](profiles/headless.toml), [bundles/base.toml](bundles/base.toml), and [bundles/headless.toml](bundles/headless.toml).
- Input: root Services and the selected Profile.
- Output: an assembled Context in which every enabled Fiber is `ACTIVE`, or a visible `RunFailure`.
- Why it exists: it makes application composition declarative. It also shows that a Bundle gives creation order while Service availability gives activation order.

### 3. Cordis runtime

- Files: [src/nano_dsh/cordis.py](src/nano_dsh/cordis.py) and [src/nano_dsh/contracts.py](src/nano_dsh/contracts.py).
- Input: Plugin Specifications, required Service names, and Plugin `apply` functions.
- Output: active Fibers, published Services, and Fiber-owned cleanup.
- Why it exists: this is the minimal dynamic lifecycle. A Consumer can remain `PENDING`, activate when a Provider arrives, return to `PENDING` if that Service disappears, and reactivate when it returns.

### 4. Agent core

- Files: [src/nano_dsh/plugins/agents.py](src/nano_dsh/plugins/agents.py), [src/nano_dsh/plugins/sessions.py](src/nano_dsh/plugins/sessions.py), [src/nano_dsh/plugins/tools.py](src/nano_dsh/plugins/tools.py), [src/nano_dsh/plugins/agent_loop.py](src/nano_dsh/plugins/agent_loop.py), [src/nano_dsh/plugins/bash.py](src/nano_dsh/plugins/bash.py), and [src/nano_dsh/plugins/editor.py](src/nano_dsh/plugins/editor.py).
- Input: a task, a Workspace, an `llm` Service, and registered Tool definitions.
- Output: an append-only Session and a final assistant response. Expected Tool Failures become Tool Results for a later Model Step.
- Why it exists: this layer keeps AgentFactory registration separate from Agent creation. It also keeps sequential Tool execution and Session state independent from the provider wire format.

### 5. Provider

- File: [src/nano_dsh/plugins/deepseek.py](src/nano_dsh/plugins/deepseek.py).
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
python -m unittest discover -s tests
```

This suite verifies the Fiber lifecycle, dynamic loading, reverse Effect cleanup, Session serialization, Reasoning Content round-trip, ordered Tool Calls, Editor confinement, Bash behavior, and a full scripted headless Agent Run.

### Three-fixture Live Acceptance Suite

The planned Live Acceptance Suite uses three disposable Bug Fixtures: one logic error, one boundary error, and one missing implementation. Each run must use the real DeepSeek API, call both `str_replace_editor` and `bash`, return Tool Results to a later Model Step, pass the fixture's `unittest` suite, and finish with final assistant text.

Its acceptance command is:

```bash
python scripts/live_acceptance.py --api-key-file .key
```

This checkout does not yet contain `fixtures/` or `scripts/live_acceptance.py`. The command is the acceptance method specified in [PLAN.md](PLAN.md), not a completed or locally runnable result. Do not report a live run as passed until those files exist and the command exits successfully. The script must not retry automatically.

## 6. Security boundary and failure behavior

- Bash is a trusted local capability. It starts in the selected Workspace, but it is not an operating-system sandbox. It can access normal host resources available to the process.
- Every Bash Tool Execution starts a fresh `/bin/bash` process. Shell state does not persist. It has a 300-second timeout and a 16,000-character model-visible output limit.
- `str_replace_editor` accepts only absolute paths. It resolves paths and rejects targets outside the Workspace, including symbolic-link escapes. This path confinement does not sandbox Bash.
- `.key` is ignored by Git. The Provider reads one non-empty line into memory. The Bash child environment removes `DEEPSEEK_API_KEY`.
- There is no automatic retry for provider requests or the planned live suite. There is no Model Step cap. A provider, configuration, Plugin, or runtime-invariant failure ends the Agent Run visibly.
- Expected Tool failures are different. Invalid Tool arguments, a nonzero Bash exit, or a non-unique editor replacement become Tool Results that the Agent can inspect in a later Model Step.

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

[docs/adr/](docs/adr/) records the hard-to-reverse choices: semantic fidelity, the dynamic Plugin lifecycle, trusted Bash, Session/Provider separation, deferred Agent creation, the code-size cap, synchronous execution, Python 3.12 with no runtime dependencies, and Tool Failure semantics.
