# Headless CLI input Service Plugin.

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nano_dsh.contracts import CommandLineArgs, HeadlessStartup, RunFailure


def apply(ctx: Any, config: Mapping[str, object]) -> None:
    if not isinstance(config, Mapping) or config:
        raise RunFailure("headless_startup Plugin config must be empty")
    args = ctx.get("cmdline_args")
    valid = (
        isinstance(args, CommandLineArgs)
        and isinstance(args.task, str)
        and isinstance(args.workspace, Path)
        and args.workspace.is_absolute()
        and args.workspace.is_dir()
        and isinstance(args.api_key_file, Path)
        and args.api_key_file.is_absolute()
    )
    if not valid:
        raise RunFailure("cmdline_args must be validated CommandLineArgs")
    ctx.provide("headless_startup", HeadlessStartup(args.task, args.workspace))
