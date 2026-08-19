# Headless Agent Run Driver Plugin.

from collections.abc import Mapping
from typing import Any

from nano_dsh.contracts import HeadlessStartup, RunFailure


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    if not isinstance(config, Mapping) or config:
        raise RunFailure("headless_runner Plugin config must be empty")
    startup = ctx.get("headless_startup")
    if not isinstance(startup, HeadlessStartup):
        raise RunFailure("headless_startup must be HeadlessStartup")
    agents = ctx.get("agents")
    ctx.emit("headless", "run started")
    final = agents.create(startup.workspace).run(startup.task)
    print(final)
    ctx.emit("headless", "run completed")
