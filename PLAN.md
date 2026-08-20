# nano-dsh Implementation Plan

## Objective

Build a minimal Python teaching implementation of the five core DeepSeek
Harness layers:

1. Apps.
2. Boot and Bundle composition.
3. A small Cordis-compatible runtime model.
4. The Agent core.
5. A real DeepSeek Provider.

The implementation must complete three real coding Agent Runs through the
DeepSeek API.

## Product Boundary

nano-dsh preserves semantic fidelity. It does not preserve the original CLI,
configuration format, package layout, or API.

The first version includes:

- Python 3.12.
- Standard-library-only production code and tests.
- One synchronous Agent.
- One global Context.
- One headless Profile.
- Two TOML Bundles.
- Nine small Plugins.
- In-memory Session Events.
- Non-streaming DeepSeek Chat Completions.
- Thinking Mode with `reasoning_effort = "high"`.
- One-shot Bash Tool Executions.
- The four-command `str_replace_editor`.
- A complete user-visible Execution Trace that starts with the System Prompt.
- No explicit `raise`, `try`, or `except` statements in repository Python.

The first version excludes:

- Web UI.
- Scope isolation.
- Session persistence.
- Streaming responses.
- Multi-Agent execution.
- Profile Patch overlays.
- Configuration hot reload.
- Transactional rollback.
- Persistent Bash or PTY support.
- Background jobs.
- An operating-system sandbox.
- Automatic API retries.
- A Model Step limit.
- Skills, Memory, and Workspace instruction loading.

## End-to-End Execution

```text
CLI
-> cmdline_args Service
-> Headless Profile
-> base and headless Bundles
-> Loader
-> Plugin Fibers
-> Service-driven activation
-> AgentLoop registers AgentFactory
-> Headless Runner calls agents.create()
-> Agent Run
-> DeepSeek Model Step
-> Tool Calls
-> Tool Results
-> later DeepSeek Model Step
-> Model Step without Tool Calls
-> require and return non-empty final content
-> reverse Effect cleanup
```

## Runtime Contracts

### Fiber lifecycle

```text
PENDING
-> LOADING
-> ACTIVE
-> PENDING when unloaded
```

- Bundle order controls Fiber creation only.
- Service availability controls Fiber activation.
- A Consumer may load before its Providers.
- Boot fails if an enabled Fiber remains `PENDING`.
- A Service name has at most one active Provider.
- Removing a Provider unloads its active Consumers.
- Restoring the Service reactivates those Consumers.
- `ctx.provide()` and `ctx.effect()` bind resources to the current Fiber.
- Normal Fiber cleanup runs disposers in reverse registration order.
- Service and AgentFactory uniqueness are internal `assert` contracts.
- Unexpected activation or cleanup errors propagate with their native traceback.

### Agent core

- AgentLoop activation registers an AgentFactory.
- AgentLoop activation does not create an Agent.
- Headless Runner starts the Execution Trace from `llm.system_prompt`.
- Headless Runner creates the Agent through the Agents Service.
- Session Events remain independent from the DeepSeek wire format.
- Assistant Session Events preserve Reasoning Content.
- Multiple Tool Calls execute sequentially in model order.
- The Agent stops when a Model Step has no Tool Calls. An `assert` requires non-empty final content.
- Predictable Tool rejections return `ToolOutput(content, failed=True)`.
- `ToolsService` returns the content to the model and traces the result as failed.
- JSON, Provider, filesystem, encoding, and timeout errors propagate unchanged.

### DeepSeek Provider

- Endpoint: `https://api.deepseek.com/chat/completions`.
- Model: `deepseek-v4-flash`.
- Thinking Mode: enabled.
- Reasoning Effort: high.
- Streaming: disabled.
- Tool choice: auto.
- API key source: `--api-key-file`, default `.key`.
- Reasoning Content is returned unchanged after thinking-mode Tool Calls.
- Protocol shape and `finish_reason` alignment are internal `assert` contracts.

### Bash Tool

- Input: `command: str`.
- Each call starts a fresh Bash process.
- The process starts in the selected Workspace.
- Shell state does not persist.
- Timeout: 300 seconds.
- Model-visible output limit: 16,000 characters.
- The child environment excludes the DeepSeek API key.
- Bash is a trusted local capability, not a sandbox.

### Editor Tool

- Public name: `str_replace_editor`.
- Paths must be absolute.
- Resolved paths must stay inside the Workspace.
- Symbolic-link escapes are rejected.
- Commands: `view`, `create`, `str_replace`, and `insert`.
- `create` does not overwrite an existing file.
- `str_replace` requires one literal match.
- `insert` validates its line position.

## Repository Structure

```text
nano-dsh/
├── pyproject.toml
├── README.md
├── README.zh-CN.md
├── CONTEXT.md
├── PLAN.md
├── docs/adr/
├── profiles/headless.toml
├── bundles/base.toml
├── bundles/headless.toml
├── nano_dsh/
│   ├── __init__.py
│   ├── __main__.py
│   ├── boot.py
│   ├── loader.py
│   ├── cordis.py
│   └── plugins/
│       ├── __init__.py
│       ├── agents.py
│       ├── sessions.py
│       ├── tools.py
│       ├── bash.py
│       ├── editor.py
│       ├── deepseek.py
│       ├── agent_loop.py
│       ├── headless_startup.py
│       └── headless_runner.py
├── tests/
└── examples/
    ├── README.md
    ├── workspaces/
    │   ├── logic-bug/
    │   ├── boundary-bug/
    │   └── missing-implementation/
    └── example.py
```

## Git Workflow

### Baseline

```text
chore: initialize the nano-dsh repository
docs(design): record the domain model and decisions
feat(contracts): define shared runtime contracts
```

### Wave 1 branches

```text
feat/runtime-fiber-lifecycle
feat/profile-loader
feat/agent-core
feat/coding-tools
feat/deepseek-provider
```

### Wave 2 branches

```text
feat/headless-app
test/live-acceptance
```

### Branch gate

1. A Worker implements only its assigned files in an independent worktree.
2. The Worker commits implementation and tests with Conventional Commits.
3. An independent read-only Review Agent inspects the branch diff.
4. The Worker fixes actionable findings on the same branch.
5. Branch tests pass.
6. The main agent merges with `--no-ff`.
7. Main tests pass after every merge.

No branch is squashed.

## Work Ownership

### `feat/runtime-fiber-lifecycle`

- `nano_dsh/cordis.py`
- Runtime tests.

### `feat/profile-loader`

- `nano_dsh/loader.py`
- `nano_dsh/boot.py`
- Loader and Boot tests.

### `feat/agent-core`

- `nano_dsh/plugins/agents.py`
- `nano_dsh/plugins/sessions.py`
- `nano_dsh/plugins/tools.py`
- `nano_dsh/plugins/agent_loop.py`
- Core tests and the Scripted Provider integration path.

### `feat/coding-tools`

- `nano_dsh/plugins/bash.py`
- `nano_dsh/plugins/editor.py`
- Tool tests.

### `feat/deepseek-provider`

- `nano_dsh/plugins/deepseek.py`
- Provider serialization and response tests.

### `feat/headless-app`

- `nano_dsh/__main__.py`
- `nano_dsh/plugins/headless_startup.py`
- `nano_dsh/plugins/headless_runner.py`
- Profiles and Bundles.
- App integration tests.

### `test/live-acceptance`

- `examples/workspaces/`.
- `examples/example.py`.
- Live acceptance assertions.

## Verification

### Offline

```bash
python -m unittest discover -v
```

The offline suite covers:

- Consumer-before-Provider activation.
- Service removal.
- Reverse Effect cleanup.
- Consumer reactivation.
- Boot failure for unresolved Fibers.
- Dynamic module loading.
- Session-to-DeepSeek serialization.
- Reasoning Content round-trip.
- Complete Execution Trace ordering and tracing-layer secret exclusion.
- Sequential Tool Calls.
- Tool argument validation.
- Bash timeout and output handling.
- Editor path confinement and command semantics.
- A complete Agent Run through the Scripted Provider.
- Production code size.

### Live

```bash
python examples/example.py --api-key-file .key
```

The Live Acceptance Suite runs three independent Bug Fixtures:

1. A logic error.
2. A boundary error.
3. A missing implementation.

Each run must:

- Use the real DeepSeek API.
- Call `str_replace_editor`.
- Call `bash`.
- Produce a later Model Step that sees Tool Results.
- Pass the fixture's `unittest` suite.
- Produce a final assistant response.

The script does not retry. Each CLI call runs in a subprocess. A failure returns
a nonzero exit status and preserves the temporary Workspace. Raw standard error
is not printed.

## Documentation

- `README.md` is English.
- `README.zh-CN.md` is Chinese.
- Both READMEs contain the same teaching sequence.
- The first explanation is one concrete end-to-end execution trace.
- The reading order follows Apps, Boot, Cordis, Core, and Provider.
- `CONTEXT.md` remains the canonical glossary.
- `docs/adr/` records hard-to-reverse decisions.

## Hard Completion Criteria

Verification evidence recorded for this revision on 2026-08-20:

- The offline suite passed 84/84 tests.
- Production Python contained 812 non-empty, non-comment lines. The largest
  production file contained 148 such lines.
- All 34 repository Python files contained zero AST `Raise`, `Try`, and
  `TryStar` nodes.
- The real-API Live Acceptance suite passed all three scenarios.

This evidence is a dated result. It does not guarantee later revisions or API
runs.

- [x] `nano-dsh` is an independent Git repository on `main`.
- [x] The parent repository ignores `/nano-dsh/`.
- [x] `.key` is ignored and absent from Git history.
- [x] All five layers and nine Plugins are implemented.
- [x] All offline tests pass.
- [x] Production Python has at most 1,000 non-empty, non-comment lines.
- [x] No production file exceeds 200 such lines.
- [x] Rerun all three Live Acceptance scenarios with a real API key.
- [x] Both READMEs are complete and synchronized.
- [x] Every feature branch passes an independent Review Agent gate.
- [x] Every feature branch is merged with `--no-ff`.
- [x] Final `main` is clean.
