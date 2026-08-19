# Separate AgentFactory registration from Agent creation

The AgentLoop Plugin registers itself as the current AgentFactory through the
Agents Service. A driver creates an Agent later through `agents.create()`.
This small indirection preserves the distinction between Plugin activation,
factory readiness, and the start of an Agent Run.
