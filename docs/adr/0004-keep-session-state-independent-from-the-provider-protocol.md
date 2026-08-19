# Keep Session state independent from the Provider protocol

nano-dsh stores Agent history as typed, in-memory Session Events. The DeepSeek
Provider converts those events into API messages for each Model Step. This
adds a small domain boundary while keeping the Agent core independent from one
Provider protocol and avoiding persistence code. Assistant Session Events
preserve Provider-owned Reasoning Content so thinking-mode Tool Calls can
continue correctly.
