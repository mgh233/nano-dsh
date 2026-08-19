# Use a synchronous execution model

nano-dsh uses synchronous Plugin lifecycles, Agent execution, DeepSeek
requests, and Tool execution. The first version has one Agent, sequential Model
Steps, sequential Tool Calls, and non-streaming responses. Async abstractions
would increase code without demonstrating an additional core mechanism.
