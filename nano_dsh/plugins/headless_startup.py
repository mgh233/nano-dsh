# Headless CLI input Service Plugin.

from typing import Any

from nano_dsh.contracts import HeadlessStartup


def apply(ctx: Any, config: object) -> None:
    args = ctx.get("cmdline_args")
    ctx.provide("headless_startup", HeadlessStartup(args.task, args.workspace))
