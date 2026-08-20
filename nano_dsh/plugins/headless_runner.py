# Headless Agent Run Driver Plugin.

from typing import Any


def apply(ctx: Any, config: object) -> None:
    startup = ctx.get("headless_startup")
    agents = ctx.get("agents")
    llm = ctx.get("llm")
    ctx.emit("system", llm.system_prompt)
    ctx.emit("user", startup.task)
    ctx.emit("headless", "run started")
    final = agents.create(startup.workspace).run(startup.task)
    print(final)
    ctx.emit("headless", "run completed")
