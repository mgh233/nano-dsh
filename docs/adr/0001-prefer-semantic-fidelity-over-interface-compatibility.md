# Prefer semantic fidelity over interface compatibility

nano-dsh preserves the core DeepSeek Harness runtime concepts and their
relationships. It does not preserve the original CLI, configuration format,
package layout, or API. This choice keeps the implementation small enough for
a new reader to understand end to end.
