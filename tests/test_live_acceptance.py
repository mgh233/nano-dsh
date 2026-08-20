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
sys.path.insert(0, str(ROOT / "examples"))
import example


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
        "FAIL",
        (
            "test_formats_a_positive_score "
            "(test_labels.FormatLabelTests."
            "test_formats_a_positive_score)",
            "test_formats_zero "
            "(test_labels.FormatLabelTests.test_formats_zero)",
        ),
    ),
}


def completed(
    command,
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class OriginalFixtureTests(unittest.TestCase):
    def test_three_original_workspaces_have_distinct_bugs(self) -> None:
        observed_failures = []
        for fixture in example.FIXTURES:
            with self.subTest(fixture=fixture.name):
                run = subprocess.run(
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
                output = run.stdout + run.stderr
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
                expected = {
                    test_id: expected_result
                    for test_id in expected_ids
                }

                self.assertEqual(run.returncode, 1)
                self.assertEqual(observed, expected)
                observed_failures.append(tuple(observed))

        self.assertEqual(len(set(observed_failures)), 3)

    def test_missing_implementation_uses_assert(self) -> None:
        source = (
            ROOT / "examples/workspaces/missing-implementation/labels.py"
        ).read_text()
        self.assertIn('assert False, "not implemented"', source)


class LiveAcceptanceTests(unittest.TestCase):
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

    def test_success_repairs_tests_and_removes_workspace(self) -> None:
        calls = []

        def run_process(command, cwd):
            calls.append((tuple(command), cwd))
            if command[1:3] == ("-m", "nano_dsh"):
                workspace = Path(command[command.index("--workspace") + 1])
                (workspace / "sample.py").write_text(
                    "def answer():\n"
                    "    return True\n"
                )
                return completed(
                    command,
                    0,
                    "Fixed.\n",
                    "tool: complete str_replace_editor\n"
                    "tool: complete bash\n"
                    "model: step 2 started\n"
                    "agent: run completed\n",
                )
            return completed(command, 0, stderr="unittest details")

        result = example._run_scenario(
            self.fixture,
            self.key_file,
            run_process=run_process,
        )

        self.assertTrue(result.passed)
        self.assertFalse(result.workspace.exists())
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], ROOT)
        self.assertEqual(calls[1][1], result.workspace)
        self.assertEqual(
            calls[0][0][calls[0][0].index("--api-key-file") + 1],
            str(self.key_file),
        )
        self.assertEqual(
            calls[1][0][1:],
            ("-m", "unittest", "discover", "-v"),
        )

    def test_incomplete_agent_trace_preserves_workspace(self) -> None:
        traces = (
            "tool: complete str_replace_editor\n",
            "tool: complete str_replace_editor\n"
            "tool: complete bash\n"
            "agent: run completed\n",
        )
        for trace in traces:
            with self.subTest(trace=trace):
                def run_process(command, cwd):
                    if command[1:3] == ("-m", "nano_dsh"):
                        return completed(command, 0, "Finished.\n", trace)
                    return completed(command, 0)

                result = example._run_scenario(
                    self.fixture,
                    self.key_file,
                    run_process=run_process,
                )

                self.assertFalse(result.passed)
                self.assertTrue(result.workspace.exists())

    def test_cli_failure_preserves_workspace(self) -> None:
        calls = []

        def run_process(command, cwd):
            calls.append(tuple(command))
            if command[1:3] == ("-m", "nano_dsh"):
                return completed(
                    command,
                    1,
                    stderr="API key and raw traceback",
                )
            return completed(command, 0)

        result = example._run_scenario(
            self.fixture,
            self.key_file,
            run_process=run_process,
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.cli_code, 1)
        self.assertEqual(result.test_code, 0)
        self.assertTrue(result.workspace.exists())
        self.assertEqual(len(calls), 2)

    def test_unittest_failure_preserves_workspace(self) -> None:
        def run_process(command, cwd):
            if command[1:3] == ("-m", "nano_dsh"):
                return completed(command, 0, "Finished.\n")
            return completed(command, 1, stderr="test failure details")

        result = example._run_scenario(
            self.fixture,
            self.key_file,
            run_process=run_process,
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.cli_code, 0)
        self.assertEqual(result.test_code, 1)
        self.assertTrue(result.workspace.exists())

    def test_output_omits_api_key_and_raw_stderr(self) -> None:
        secret = "do-not-print-this-key"

        def run_process(command, cwd):
            return completed(command, 1, stderr=secret)

        result = example._run_scenario(
            self.fixture,
            self.key_file,
            run_process=run_process,
        )
        output = StringIO()
        with redirect_stdout(output):
            example._print_result(result)

        self.assertNotIn(secret, output.getvalue())
        self.assertNotIn("stderr", output.getvalue())

    def test_suite_summary_and_exit_code(self) -> None:
        calls = 0

        def run_process(command, cwd):
            nonlocal calls
            calls += 1
            if command[1:3] == ("-m", "nano_dsh"):
                return completed(command, 1, stderr="private")
            return completed(command, 0)

        output = StringIO()
        with redirect_stdout(output):
            exit_code = example.run_suite(
                self.key_file,
                fixtures=(self.fixture, self.fixture, self.fixture),
                run_process=run_process,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(calls, 6)
        self.assertIn("Summary: 0/3 PASS", output.getvalue())

    def test_argument_path_is_absolute_without_reading_key(self) -> None:
        with patch.object(Path, "read_text", side_effect=AssertionError):
            parsed = example._parse_args(
                ["--api-key-file", str(self.key_file)]
            )

        self.assertEqual(parsed, self.key_file)
        self.assertTrue(parsed.is_absolute())


if __name__ == "__main__":
    unittest.main()
