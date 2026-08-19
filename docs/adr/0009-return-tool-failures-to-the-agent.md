# Return Tool Failures to the Agent

Expected Tool failures become Tool Results so the Agent can inspect and recover
from them. Examples include a nonzero Bash exit and a non-unique Editor
replacement. Configuration errors, Plugin failures, Provider failures, and
runtime invariant violations propagate visibly and end the Agent Run.
Each Tool validates its own model-generated arguments before execution.
Invalid arguments become a Tool Failure rather than reaching the subprocess or
filesystem operation.
Each Bash Tool Execution has a 300-second timeout and returns at most 16,000
characters. A timeout becomes a Tool Failure that the Agent can inspect.
