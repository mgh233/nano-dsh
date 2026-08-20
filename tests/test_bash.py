from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nano_dsh.contracts import ToolOutput
from nano_dsh.plugins import bash


class FakeTools:
    def __init__(self) -> None:
        self.definition = None

    def register(self, definition):
        self.definition = definition
        return lambda: None


class FakeContext:
    def __init__(self) -> None:
        self.tools = FakeTools()
        self.effect_used = False

    def get(self, name: str):
        return self.tools

    def effect(self, setup) -> None:
        self.effect_used = True
        self.disposer = setup()


class BashToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.ctx = FakeContext()
        bash.apply(self.ctx, {})
        self.definition = self.ctx.tools.definition
        self.handler = self.definition.handler

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_schema_and_effect_registration(self) -> None:
        self.assertEqual(self.definition.name, "bash")
        self.assertTrue(self.ctx.effect_used)
        self.assertEqual(self.definition.parameters["required"], ["command"])
        self.assertEqual(
            set(self.definition.parameters["properties"]),
            {"command"},
        )
        self.assertFalse(self.definition.parameters["additionalProperties"])

    def test_plugin_config_is_trusted_after_loading(self) -> None:
        context = FakeContext()
        bash.apply(context, {"timeout": 1})
        self.assertEqual(context.tools.definition.name, "bash")

    def test_runs_in_workspace(self) -> None:
        result = self.handler({"command": "pwd"}, self.workspace)
        self.assertEqual(Path(result.content.strip()).resolve(), self.workspace.resolve())

    def test_merges_stdout_and_stderr(self) -> None:
        result = self.handler(
            {"command": "printf out; printf err >&2"},
            self.workspace,
        )
        self.assertEqual(result.content, "outerr")

    def test_nonzero_exit_returns_output_and_marker(self) -> None:
        result = self.handler(
            {"command": "printf failed; exit 7"},
            self.workspace,
        )
        self.assertTrue(result.failed)
        self.assertIn("failed", result.content)
        self.assertTrue(result.content.endswith("[exit code: 7]"))

    def test_missing_or_non_string_command_returns_failure_output(self) -> None:
        for arguments in ({}, {"command": 3}, {"command": "true", "extra": True}):
            with self.subTest(arguments=arguments):
                result = self.handler(arguments, self.workspace)
                self.assertEqual(result, ToolOutput("Error: bash requires a string command", True))

    def test_secret_is_removed_from_child_environment(self) -> None:
        command = (
            'if [[ ${DEEPSEEK_API_KEY+x} == x ]]; then printf present; '
            "else printf absent; fi"
        )
        with mock.patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "must-not-leak"},
        ):
            result = self.handler({"command": command}, self.workspace)
        self.assertEqual(result.content, "absent")

    def test_output_is_truncated(self) -> None:
        result = self.handler(
            {"command": "printf 'x%.0s' {1..17000}"},
            self.workspace,
        )
        self.assertEqual(len(result.content), 16_000)
        self.assertEqual(set(result.content), {"x"})


if __name__ == "__main__":
    unittest.main()
