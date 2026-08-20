# Return predictable Tool failures to the Agent

A predictable Tool rejection returns `ToolOutput(content, failed=True)`.
Examples include an unknown Tool, a nonzero Bash exit, and an invalid Editor
operation. `ToolsService` writes the content to the Session as a Tool Result and
records a failed trace. The Agent can inspect it in the next Model Step.

Internal invariants use concise `assert` statements. JSON, network, filesystem,
encoding, and subprocess timeout errors are not translated. They propagate with
their native Python traceback. The teaching implementation intentionally uses
no explicit `raise`, `try`, or `except` statements.
