from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import live_acceptance


GOOD_TRACE = """\
headless: run started
agent: run started
model: step 1 started
model: request
model: response
model: step 1 completed
tool: execute str_replace_editor
tool: complete str_replace_editor
tool: execute bash
tool: complete bash
model: step 2 started
model: request
model: response
model: step 2 completed
agent: run completed
headless: run completed
"""

EXPECTED_FIXTURE_RESULTS = {
    "logic-bug": (
        "FAIL",
        (
            "test_all_units_can_be_reserved "
            "(test_inventory.AvailableUnitsTests."
            "test_all_units_can_be_reserved)",
            "test_subtracts_reserved_units "
            "(test_inventory.AvailableUnitsTests."
            "test_subtracts_reserved_units)",
        ),
    ),
    "boundary-bug": (
        "FAIL",
        (
            "test_keeps_a_complete_final_batch "
            "(test_batches.MakeBatchesTests."
            "test_keeps_a_complete_final_batch)",
            "test_keeps_a_short_final_batch "
            "(test_batches.MakeBatchesTests."
            "test_keeps_a_short_final_batch)",
        ),
    ),
    "missing-implementation": (
        "ERROR",
        (
            "test_formats_a_positive_score "
            "(test_labels.FormatLabelTests."
            "test_formats_a_positive_score)",
            "test_formats_zero "
            "(test_labels.FormatLabelTests.test_formats_zero)",
        ),
    ),
}


class OriginalFixtureTests(unittest.TestCase):
    def test_each_original_fixture_has_its_expected_failure(self) -> None:
        for fixture in live_acceptance.FIXTURES:
            with self.subTest(fixture=fixture.name):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "unittest",
                        "discover",
                        "-v",
                    ],
                    cwd=fixture,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                output = completed.stdout + completed.stderr
                observed = {
                    test_id: result
                    for test_id, result in re.findall(
                        r"^(test_[^\n]+) \.\.\. (FAIL|ERROR|ok)$",
                        output,
                        re.MULTILINE,
                    )
                }
                expected_result, expected_ids = EXPECTED_FIXTURE_RESULTS[
                    fixture.name
                ]

                self.assertEqual(completed.returncode, 1)
                self.assertIn("Ran 2 tests", output)
                self.assertEqual(
                    observed,
                    {
                        test_id: expected_result
                        for test_id in expected_ids
                    },
                )
                if expected_result == "FAIL":
                    self.assertIn("FAILED (failures=2)", output)
                    self.assertIn("AssertionError", output)
                    self.assertNotIn("NotImplementedError", output)
                else:
                    self.assertIn("FAILED (errors=2)", output)
                    self.assertIn("NotImplementedError", output)


class LiveAcceptanceHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = self.root / "logic-bug"
        self.fixture.mkdir()
        (self.fixture / "sample.py").write_text(
            "def answer():\n"
            "    return False\n"
        )
        (self.fixture / "test_sample.py").write_text(
            "import unittest\n"
            "from sample import answer\n\n"
            "class SampleTests(unittest.TestCase):\n"
            "    def test_answer(self):\n"
            "        self.assertTrue(answer())\n"
        )
        self.key_file = (self.root / "api-key").resolve()

    def repair(self, arguments: list[str]) -> None:
        index = arguments.index("--workspace") + 1
        workspace = Path(arguments[index])
        (workspace / "sample.py").write_text(
            "def answer():\n"
            "    return True\n"
        )

    def test_invoke_cli_captures_stdout_and_stderr(self) -> None:
        def fake_main(arguments: list[str]) -> None:
            print("done")
            print("model: step 1 started", file=sys.stderr)

        with patch.object(live_acceptance, "nano_dsh_main", fake_main):
            stdout, stderr = live_acceptance._invoke_cli(["task"])

        self.assertEqual(stdout, "done\n")
        self.assertEqual(stderr, "model: step 1 started\n")

    def test_invoke_cli_sanitizes_trace_when_main_raises(self) -> None:
        def fake_main(arguments: list[str]) -> None:
            print("tool: execute bash", file=sys.stderr)
            print("reasoning: do-not-print-this-key", file=sys.stderr)
            raise RuntimeError("do-not-print-this-key")

        with patch.object(live_acceptance, "nano_dsh_main", fake_main):
            with self.assertRaises(
                live_acceptance.CliInvocationFailure
            ) as caught:
                live_acceptance._invoke_cli(["task"])

        self.assertEqual(caught.exception.trace, ("tool: execute bash",))
        self.assertNotIn("do-not-print-this-key", str(caught.exception))

    def test_success_calls_cli_once_runs_gate_and_cleans_workspace(self) -> None:
        calls = []

        def invoke(arguments: list[str]) -> tuple[str, str]:
            calls.append(arguments)
            self.repair(arguments)
            return "Fixed.\n", GOOD_TRACE

        result = live_acceptance._run_fixture(
            self.fixture,
            self.key_file,
            invoke_cli=invoke,
        )

        self.assertTrue(result.passed)
        self.assertEqual(len(calls), 1)
        self.assertFalse(result.workspace.exists())
        self.assertIn(str(result.workspace), calls[0][0])
        self.assertIn("str_replace_editor", calls[0][0])
        self.assertIn("Use bash", calls[0][0])
        self.assertIn("unittest discover -v", calls[0][0])
        self.assertIn("Do not modify the test files", calls[0][0])
        self.assertEqual(
            calls[0][calls[0].index("--api-key-file") + 1],
            str(self.key_file),
        )

    def test_cli_exception_is_not_retried_and_workspace_is_preserved(self) -> None:
        calls = 0

        def invoke(arguments: list[str]) -> tuple[str, str]:
            nonlocal calls
            calls += 1
            raise RuntimeError("secret key and private reasoning")

        result = live_acceptance._run_fixture(
            self.fixture,
            self.key_file,
            invoke_cli=invoke,
        )

        self.assertFalse(result.passed)
        self.assertEqual(calls, 1)
        self.assertTrue(result.workspace.exists())
        self.assertEqual(result.detail, "CLI/main flow raised an exception")

    def test_trace_contract_failures_preserve_workspace(self) -> None:
        cases = {
            "empty final": (" \n", GOOD_TRACE),
            "failed-only tools": (
                "done\n",
                GOOD_TRACE
                .replace(
                    "tool: complete str_replace_editor",
                    "tool: failed str_replace_editor",
                )
                .replace("tool: complete bash", "tool: failed bash"),
            ),
            "missing Provider request": (
                "done\n",
                GOOD_TRACE.replace(
                    "model: step 2 started\nmodel: request\n",
                    "model: step 2 started\n",
                ),
            ),
            "missing Provider response": (
                "done\n",
                GOOD_TRACE.replace(
                    "model: step 2 started\n"
                    "model: request\nmodel: response\n"
                    "model: step 2 completed",
                    "model: step 2 started\n"
                    "model: request\nmodel: step 2 completed",
                ),
            ),
            "later Model Step out of order": (
                "done\n",
                GOOD_TRACE.replace(
                    "model: step 2 started\n"
                    "model: request\nmodel: response\n"
                    "model: step 2 completed",
                    "model: step 2 started\n"
                    "model: response\nmodel: request\n"
                    "model: step 2 completed",
                ),
            ),
            "missing Headless lifecycle": (
                "done\n",
                GOOD_TRACE.replace("headless: run completed\n", ""),
            ),
            "Tool event after Agent completion": (
                "done\n",
                GOOD_TRACE.replace(
                    "agent: run completed\n",
                    "agent: run completed\ntool: execute bash\n",
                ),
            ),
        }
        for name, response in cases.items():
            with self.subTest(name=name):
                result = live_acceptance._run_fixture(
                    self.fixture,
                    self.key_file,
                    invoke_cli=lambda _: response,
                    run_tests=lambda _: True,
                )
                self.assertFalse(result.passed)
                self.assertTrue(result.workspace.exists())

    def test_duplicate_lifecycle_events_are_rejected(self) -> None:
        lifecycle_events = (
            "headless: run started",
            "agent: run started",
            "agent: run completed",
            "headless: run completed",
        )
        for event in lifecycle_events:
            with self.subTest(event=event):
                trace = GOOD_TRACE.replace(event, f"{event}\n{event}")
                result = live_acceptance._run_fixture(
                    self.fixture,
                    self.key_file,
                    invoke_cli=lambda _: ("done\n", trace),
                    run_tests=lambda _: True,
                )
                self.assertFalse(result.passed)
                self.assertTrue(result.workspace.exists())

    def test_independent_unittest_gate_rejects_an_unfixed_workspace(self) -> None:
        result = live_acceptance._run_fixture(
            self.fixture,
            self.key_file,
            invoke_cli=lambda _: ("done\n", GOOD_TRACE),
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            result.detail,
            "independent unittest verification failed",
        )
        self.assertTrue(result.workspace.exists())

    def test_failure_output_does_not_leak_key_or_untrusted_trace(self) -> None:
        secret = "do-not-print-this-key"
        unsafe_trace = (
            GOOD_TRACE
            + f"reasoning: {secret}\n"
            + "http: https://api.deepseek.com/full-response\n"
            + "file: complete source text\n"
        )
        result = live_acceptance._run_fixture(
            self.fixture,
            self.key_file,
            invoke_cli=lambda _: ("done\n", unsafe_trace),
            run_tests=lambda _: False,
        )
        output = StringIO()
        with redirect_stdout(output):
            live_acceptance._print_result(result)

        text = output.getvalue()
        self.assertNotIn(secret, text)
        self.assertNotIn("private reasoning", text)
        self.assertNotIn("https://", text)
        self.assertNotIn("complete source text", text)
        self.assertIn("Sanitized Execution Trace:", text)

    def test_suite_calls_each_fixture_once_and_returns_nonzero(self) -> None:
        calls = 0

        def invoke(arguments: list[str]) -> tuple[str, str]:
            nonlocal calls
            calls += 1
            raise RuntimeError("do-not-print-this-key")

        output = StringIO()
        with redirect_stdout(output):
            exit_code = live_acceptance.run_suite(
                self.key_file,
                fixtures=(self.fixture, self.fixture, self.fixture),
                invoke_cli=invoke,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(calls, 3)
        self.assertIn("Summary: 0/3 PASS", output.getvalue())
        self.assertNotIn("do-not-print-this-key", output.getvalue())

    def test_argument_path_is_absolute_without_reading_key(self) -> None:
        with patch.object(Path, "read_text", side_effect=AssertionError):
            parsed = live_acceptance._parse_args(
                ["--api-key-file", str(self.key_file)]
            )

        self.assertTrue(parsed.is_absolute())
        self.assertEqual(parsed, self.key_file)


if __name__ == "__main__":
    unittest.main()
