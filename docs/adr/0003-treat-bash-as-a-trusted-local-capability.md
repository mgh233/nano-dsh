# Treat Bash as a trusted local capability

nano-dsh confines Editor Tool paths to the selected Workspace, but runs each
Bash Tool call as a normal host subprocess with that Workspace as its current
directory. It does not claim to sandbox Bash. Live acceptance uses a disposable
Workspace and keeps the DeepSeek API key out of the Bash subprocess environment.
The CLI reads the key from an explicit `--api-key-file` path whose default is
`.key`. The Provider keeps the value in memory, and `.key` is ignored by Git.
The Editor Tool follows the original absolute-path contract, but resolves each
path and rejects targets outside the selected Workspace.
