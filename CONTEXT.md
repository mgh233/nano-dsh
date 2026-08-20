# nano-dsh

nano-dsh is a minimal teaching implementation of the core DeepSeek Harness
runtime model. It keeps the concepts required to explain one complete Agent
execution without reproducing the full product.

## Language

**Agent Run**:
One task execution from user input to the final assistant response. An Agent
Run can contain multiple Model Steps and Tool Executions.
_Avoid_: Agent flow, request

**Live Acceptance Run**:
An Agent Run that uses the real DeepSeek API, performs at least one Tool
Execution, and then gives the Tool Result to a later Model Step before the
final response.
_Avoid_: API smoke test, text completion test

**Bug Fixture**:
A disposable Python Workspace with a focused defect and a failing `unittest`
suite used by a Live Acceptance Run.
_Avoid_: Example project, benchmark

**Live Acceptance Suite**:
The three Live Acceptance Runs for the logic, boundary, and missing-
implementation Bug Fixtures.
_Avoid_: Unit tests, integration tests

**Execution Trace**:
A user-visible transcript that starts with the System Prompt. It includes the
User Task, Reasoning Content, assistant content, Tool Calls, Tool Results, and
runtime events. The tracing layer does not record the Provider API key or HTTP
headers. Tool output is printed verbatim, so a Tool can expose a secret it reads.
_Avoid_: Debug log, HTTP trace

**Model Step**:
One request from an Agent to an LLM Provider together with the resulting model
response.
_Avoid_: Turn, completion

**Reasoning Content**:
Provider-owned reasoning data attached to an assistant Session Event and
returned unchanged to the next Model Step when Tool Calls continue the run.
_Avoid_: Final response, Tool Result

**Tool Call**:
A model request to invoke one named Tool with structured arguments.
_Avoid_: Function call, action

**Tool Execution**:
The runtime processing of one Tool Call.
_Avoid_: Tool use, command

**Tool Result**:
The value produced by a Tool Execution and returned to a later Model Step.
_Avoid_: Tool response, observation

**Failed Tool Output**:
A predictable unsuccessful Tool Execution represented by
`ToolOutput(content, failed=True)`. Its content becomes a Tool Result.
_Avoid_: Exception wrapper

**Native Python Failure**:
An unexpected JSON, network, filesystem, encoding, timeout, or runtime error
that propagates with its original traceback.
_Avoid_: Result wrapper, fallback

**Tool**:
A named operation that an Agent can request through a Tool Call.
_Avoid_: Function, command

**Bash Tool**:
A Tool that executes one command in a fresh Bash process rooted at the Agent
workspace. Shell state does not persist between Tool Executions.
_Avoid_: Terminal, persistent shell

**Editor Tool**:
The Tool exposed as `str_replace_editor`. It views, creates, and changes text
files through exact replacement or line insertion. It accepts only absolute
paths inside the Workspace.
_Avoid_: Patch Tool, text editor

**Unique Replacement**:
An Editor Tool change that proceeds only when the old text occurs exactly once
in the target file.
_Avoid_: Search and replace, fuzzy replacement

**Workspace**:
The root directory selected for one Agent Run. Editor Tool paths must remain
inside this directory.
_Avoid_: Repository, current directory

**Trusted Local Run**:
An Agent Run in which the Bash Tool has normal host-process access even though
it starts in the Workspace.
_Avoid_: Sandboxed Run, isolated Run

### Agent State

**Session**:
The append-only, in-memory record of the user messages, assistant messages,
Tool Calls, and Tool Results produced during one Agent Run.
_Avoid_: Chat history, API messages

**Session Event**:
One typed record appended to a Session.
_Avoid_: Message, log entry

**Agent**:
The runtime object that advances one Session through Model Steps and Tool
Executions until it produces a final assistant response.
_Avoid_: AgentLoop, assistant

**AgentFactory**:
The capability that creates an Agent.
_Avoid_: Agent builder, AgentLoop

**Agents Service**:
The Service that owns the current AgentFactory and exposes Agent creation to
drivers.
_Avoid_: Agent registry, Agent manager

**AgentLoop**:
The AgentFactory that advances Agents through Model Steps and Tool Executions.
Activating it registers a factory but does not start an Agent Run.
_Avoid_: Agent, Runner

**Driver**:
A Plugin that starts an Agent Run after its required Services become available.
_Avoid_: AgentLoop, entry point

**Headless Startup Service**:
The CLI-derived task and Workspace that make a headless Agent Run ready to
start.
_Avoid_: Command arguments, Runner configuration

**Headless Runner**:
The Driver that starts the Execution Trace from the LLM Provider's System
Prompt, then creates an Agent after the Headless Startup, Agents, and LLM
Services become available.
_Avoid_: AgentLoop, CLI

**Semantic Fidelity**:
Preservation of the core runtime concepts and their relationships without
preserving the original CLI, configuration format, package layout, or API.
_Avoid_: Interface compatibility, source port

### Runtime Composition

**Context**:
The runtime environment that stores Services and resolves the Service
requirements of Fibers.
_Avoid_: Container, registry

**Plugin**:
A loadable unit that contributes one capability to the running application and
owns the resources created during its activation.
_Avoid_: Component, extension

**Service**:
A named capability published by exactly one Provider in the runtime Context.
Plugins depend on Service names instead of concrete Plugin identities.
_Avoid_: Dependency, singleton

**Provider**:
A Plugin that publishes a Service.
_Avoid_: Service Plugin

**DeepSeek Provider**:
The Provider that converts Session Events and Tool definitions into DeepSeek
requests and converts DeepSeek responses into Agent inputs.
_Avoid_: AgentLoop, HTTP client

**Scripted Provider**:
A deterministic test Provider that returns a fixed sequence of assistant
responses without network access.
_Avoid_: Mock API, fake Agent

**Consumer**:
A Plugin that declares one or more required Services.
_Avoid_: Dependent Plugin

**Fiber**:
One applied instance of a Plugin. A Fiber tracks that instance's dependency
state, lifecycle state, and owned Effects.
_Avoid_: Plugin, task

**Fiber State**:
One of `PENDING`, `LOADING`, or `ACTIVE`. It states whether a Fiber is waiting,
activating, or active.
_Avoid_: Plugin status, Agent state

**Effect**:
A resource-producing action owned by a Fiber together with the action that
releases that resource.
_Avoid_: Side effect, callback

### Application Assembly

**Boot**:
The process that selects a Profile, loads its Bundles, and verifies that every
enabled Fiber is active before a Driver starts an Agent Run.
_Avoid_: Startup, CLI

**Loader**:
The runtime component that turns Plugin Specifications into dynamically
imported Plugin Fibers.
_Avoid_: Importer, Boot

**Bundle**:
An ordered group of Plugin specifications that contributes one coherent set of
capabilities to an application.
_Avoid_: Package, module group

**Profile**:
A named application assembly that selects an ordered list of Bundles.
_Avoid_: Environment, preset

**Plugin Specification**:
A declarative Bundle entry that gives one Plugin a stable identifier, an
importable module name, required Services, and configuration.
_Avoid_: Manifest, Plugin metadata
