from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nano_dsh.contracts import RunFailure, ToolFailure
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
        if name != "tools":
            raise KeyError(name)
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

    def test_nonempty_config_fails(self) -> None:
        with self.assertRaises(RunFailure):
            bash.apply(FakeContext(), {"timeout": 1})

    def test_runs_in_workspace(self) -> None:
        result = self.handler({"command": "pwd"}, self.workspace)
        self.assertEqual(Path(result.strip()).resolve(), self.workspace.resolve())

    def test_merges_stdout_and_stderr(self) -> None:
        result = self.handler(
            {"command": "printf out; printf err >&2"},
            self.workspace,
        )
        self.assertEqual(result, "outerr")

    def test_nonzero_exit_returns_output_and_marker(self) -> None:
        result = self.handler(
            {"command": "printf failed; exit 7"},
            self.workspace,
        )
        self.assertIn("failed", result)
        self.assertTrue(result.endswith("[exit code: 7]"))

    def test_timeout_is_a_tool_failure(self) -> None:
        with mock.patch.object(bash, "TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(ToolFailure, "timed out"):
                self.handler({"command": "sleep 1"}, self.workspace)

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
        self.assertEqual(result, "absent")

    def test_invalid_arguments_fail_before_execution(self) -> None:
        invalid = (
            None,
            {},
            {"command": 3},
            {"command": "true", "extra": True},
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ToolFailure):
                    self.handler(arguments, self.workspace)

    def test_output_is_truncated(self) -> None:
        result = self.handler(
            {"command": "printf 'x%.0s' {1..17000}"},
            self.workspace,
        )
        self.assertEqual(len(result), 16_000)
        self.assertEqual(set(result), {"x"})


if __name__ == "__main__":
    unittest.main()
