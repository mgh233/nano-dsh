# Headless Agent Run Driver Plugin.

from typing import Any


def apply(ctx: Any, config: object) -> None:
    startup = ctx.get("headless_startup")
    agents = ctx.get("agents")
    ctx.emit("headless", "run started")
    final = agents.create(startup.workspace).run(startup.task)
    print(final)
    ctx.emit("headless", "run completed")
