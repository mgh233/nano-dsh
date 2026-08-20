from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import chdir, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from nano_dsh.__main__ import _parse_args, main
from nano_dsh.contracts import CommandLineArgs, PluginSpec
from nano_dsh.cordis import Context
from nano_dsh.loader import read_bundle, read_profile
from nano_dsh.plugins import headless_runner, headless_startup


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles/headless.toml"
TEST_KEY = "offline-test-key"
REASONING = "private reasoning must round-trip unchanged"
FINAL = "Task complete."


class ScriptedTransport:
    def __init__(self, target: Path) -> None:
        self.target = target
        self.requests: list[dict[str, object]] = []

    def __call__(self, request: object) -> bytes:
        payload = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        self.requests.append(payload)
        if len(self.requests) == 1:
            return self._tools_response()
        return self._final_response()

    def _tools_response(self) -> bytes:
        editor_arguments = json.dumps({
            "command": "str_replace",
            "path": str(self.target),
            "old_str": "before\n",
            "new_str": "after\n",
        })
        bash_arguments = json.dumps({
            "command": "printf 'BASH:%s' \"$(cat target.txt)\"",
        })
        return json.dumps({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": REASONING,
                    "tool_calls": [
                        {
                            "id": "edit-1",
                            "type": "function",
                            "function": {
                                "name": "str_replace_editor",
                                "arguments": editor_arguments,
                            },
                        },
                        {
                            "id": "bash-1",
                            "type": "function",
                            "function": {
                                "name": "bash",
                                "arguments": bash_arguments,
                            },
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }],
        }).encode()

    def _final_response(self) -> bytes:
        return json.dumps({
            "choices": [{
                "message": {"role": "assistant", "content": FINAL},
                "finish_reason": "stop",
            }],
        }).encode()


class HeadlessAppTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name).resolve()
        self.target = self.workspace / "target.txt"
        self.target.write_text("before\n")
        self.key_file = self.workspace / "test.key"
        self.key_file.write_text(TEST_KEY + "\n")

    def test_real_cli_runs_nine_plugins_tools_and_cleanup(self) -> None:
        transport = ScriptedTransport(self.target)
        stdout = StringIO()
        stderr = StringIO()
        with (
            patch("nano_dsh.plugins.deepseek._send", transport),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            main([
                "fix target.txt",
                "--workspace",
                str(self.workspace),
                "--api-key-file",
                str(self.key_file),
            ])

        self.assertEqual(stdout.getvalue(), FINAL + "\n")
        self.assertEqual(self.target.read_text(), "after\n")
        self.assertEqual(len(transport.requests), 2)
        second_messages = transport.requests[1]["messages"]
        assistant = second_messages[-3]
        self.assertEqual(assistant["reasoning_content"], REASONING)
        self.assertEqual(
            [call["function"]["name"] for call in assistant["tool_calls"]],
            ["str_replace_editor", "bash"],
        )
        self.assertIn("BASH:after", second_messages[-1]["content"])

        trace = stderr.getvalue().splitlines()
        self.assertTrue(all(": " in line for line in trace))
        self.assertIn("headless: run started", trace)
        self.assertIn("headless: run completed", trace)
        self.assertEqual(sum(line.endswith("-> ACTIVE") for line in trace), 9)
        self.assertEqual(sum(line.endswith("ACTIVE -> PENDING") for line in trace), 9)
        self.assertNotIn(TEST_KEY, stderr.getvalue())
        self.assertNotIn(REASONING, stderr.getvalue())

    def test_profile_has_exact_order_and_configuration(self) -> None:
        profile = read_profile(PROFILE)
        self.assertEqual(
            profile.bundles,
            (
                (ROOT / "bundles/base.toml").resolve(),
                (ROOT / "bundles/headless.toml").resolve(),
            ),
        )
        specs = tuple(
            spec
            for bundle in profile.bundles
            for spec in read_bundle(bundle).plugins
        )
        self.assertEqual(
            [spec.id for spec in specs],
            [
                "sessions",
                "agents",
                "tools",
                "bash",
                "editor",
                "deepseek",
                "agent_loop",
                "headless_startup",
                "headless_runner",
            ],
        )
        self.assertEqual(
            [spec.inject for spec in specs],
            [
                (),
                (),
                (),
                ("tools",),
                ("tools",),
                ("cmdline_args",),
                ("sessions", "agents", "tools", "llm"),
                ("cmdline_args",),
                ("headless_startup", "agents"),
            ],
        )
        self.assertEqual(specs[5].config, {
            "model": "deepseek-v4-flash",
            "thinking": "enabled",
            "reasoning_effort": "high",
            "stream": False,
        })

    def test_argument_defaults_are_absolute(self) -> None:
        default_key = self.workspace / ".key"
        default_key.write_text(TEST_KEY + "\n")
        with chdir(self.workspace):
            args = _parse_args(["task"])
        self.assertEqual(
            args,
            CommandLineArgs("task", self.workspace, default_key),
        )

    def test_argument_paths_resolve_to_absolute_paths(self) -> None:
        with chdir(self.workspace.parent):
            args = _parse_args([
                "task",
                "--workspace",
                self.workspace.name,
                "--api-key-file",
                f"{self.workspace.name}/test.key",
            ])
        self.assertTrue(args.workspace.is_absolute())
        self.assertTrue(args.api_key_file.is_absolute())
        self.assertEqual(args.workspace, self.workspace)
        self.assertEqual(args.api_key_file, self.key_file)

    def test_missing_workspace_is_rejected(self) -> None:
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as raised:
                _parse_args([
                    "task",
                    "--workspace",
                    str(self.workspace / "missing"),
                ])
        self.assertEqual(raised.exception.code, 2)

    def test_task_is_required(self) -> None:
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as raised:
                _parse_args([])
        self.assertEqual(raised.exception.code, 2)

    def test_startup_publishes_headless_startup(self) -> None:
        args = CommandLineArgs("task", self.workspace, self.key_file)
        context = Context()
        context.provide_root("cmdline_args", args)
        context.add_fiber(
            PluginSpec(
                "startup",
                "nano_dsh.plugins.headless_startup",
                ("cmdline_args",),
            ),
            lambda ctx: headless_startup.apply(ctx, {}),
        )
        self.assertEqual(
            context.get("headless_startup").workspace,  # type: ignore[attr-defined]
            self.workspace,
        )
        context.dispose()


if __name__ == "__main__":
    unittest.main()
