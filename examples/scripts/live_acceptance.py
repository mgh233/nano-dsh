"""Run the three nano-dsh Live Acceptance scenarios."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Callable, Sequence


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nano_dsh.__main__ import main as nano_dsh_main


FIXTURES = (
    ROOT / "examples/fixtures/logic-bug",
    ROOT / "examples/fixtures/boundary-bug",
    ROOT / "examples/fixtures/missing-implementation",
)
TASK_OBJECTIVES = {
    "logic-bug": "Correct the inventory availability calculation.",
    "boundary-bug": "Correct batch splitting at the end of the input.",
    "missing-implementation": "Implement the label formatting contract.",
}
TRACE_PATTERNS = (
    re.compile(r"fiber: [a-z_]+: PENDING"),
    re.compile(
        r"fiber: [a-z_]+: "
        r"(?:PENDING|LOADING|ACTIVE|UNLOADING|FAILED) -> "
        r"(?:PENDING|LOADING|ACTIVE|UNLOADING|FAILED|DISPOSED)"
    ),
    re.compile(r"service: [a-z_]+: provided by (?:root|[a-z_]+)"),
    re.compile(r"service: [a-z_]+: removed"),
    re.compile(r"(?:headless|agent): run (?:started|completed)"),
    re.compile(r"model: (?:request|response)"),
    re.compile(r"model: step [1-9][0-9]* (?:started|completed)"),
    re.compile(
        r"tool: (?:execute|complete|failed) (?:str_replace_editor|bash)"
    ),
)

InvokeCli = Callable[[Sequence[str]], tuple[str, str]]
RunTests = Callable[[Path], bool]


@dataclass(frozen=True)
class AcceptanceResult:
    fixture: str
    workspace: Path
    passed: bool
    detail: str
    trace: tuple[str, ...]


class AcceptanceFailure(Exception):
    """A sanitized Live Acceptance assertion failure."""


class CliInvocationFailure(Exception):
    """A CLI failure with only its sanitized Execution Trace."""

    def __init__(self, trace: tuple[str, ...]) -> None:
        super().__init__("CLI/main flow raised an exception")
        self.trace = trace


def _parse_args(argv: Sequence[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key-file", default=".key")
    values = parser.parse_args(argv)
    return Path(values.api_key_file).resolve()


def _invoke_cli(arguments: Sequence[str]) -> tuple[str, str]:
    stdout = StringIO()
    stderr = StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            nano_dsh_main(list(arguments))
    except Exception:
        raise CliInvocationFailure(_safe_trace(stderr.getvalue())) from None
    return stdout.getvalue(), stderr.getvalue()


def _safe_trace(stderr: str) -> tuple[str, ...]:
    """Keep only known concise events from the captured Execution Trace."""

    events = []
    for line in stderr.splitlines():
        if any(pattern.fullmatch(line) for pattern in TRACE_PATTERNS):
            events.append(line)
            continue
        other_tool = re.fullmatch(
            r"tool: (execute|complete|failed) .+",
            line,
        )
        if other_tool is not None:
            events.append(f"tool: {other_tool.group(1)} <other>")
    return tuple(events)


def _assert_run(stdout: str, trace: tuple[str, ...]) -> None:
    if not stdout.strip():
        raise AcceptanceFailure("final response is empty")

    headless_started = _single_event(trace, "headless: run started")
    agent_started = _single_event(trace, "agent: run started")
    agent_completed = _single_event(trace, "agent: run completed")
    headless_completed = _single_event(trace, "headless: run completed")
    if not (
        headless_started
        < agent_started
        < agent_completed
        < headless_completed
    ):
        raise AcceptanceFailure("Agent and Headless lifecycle is out of order")
    if any(
        not agent_started < index < agent_completed
        for index, event in enumerate(trace)
        if event.startswith(("model: ", "tool: "))
    ):
        raise AcceptanceFailure(
            "Model or Tool event is outside the Agent lifecycle"
        )

    _successful_tool_completions(
        trace,
        "str_replace_editor",
    )
    _successful_tool_completions(
        trace,
        "bash",
    )
    last_tool_terminated = max(
        index
        for index, event in enumerate(trace)
        if event.startswith(("tool: complete ", "tool: failed "))
    )
    if not _has_later_model_step(
        trace,
        last_tool_terminated,
        agent_completed,
    ):
        raise AcceptanceFailure(
            "no complete Model Step follows the last Tool result"
        )


def _single_event(trace: tuple[str, ...], event: str) -> int:
    indexes = [
        index
        for index, candidate in enumerate(trace)
        if candidate == event
    ]
    if len(indexes) != 1:
        raise AcceptanceFailure(f"expected exactly one trace event: {event}")
    return indexes[0]


def _successful_tool_completions(
    trace: tuple[str, ...],
    tool: str,
) -> tuple[int, ...]:
    execute_event = f"tool: execute {tool}"
    complete_event = f"tool: complete {tool}"
    executions = [
        index
        for index, event in enumerate(trace)
        if event == execute_event
    ]
    completions = tuple(
        index
        for index, event in enumerate(trace)
        if event == complete_event
    )
    if not executions or not completions:
        raise AcceptanceFailure(
            f"Tool did not execute and complete successfully: {tool}"
        )
    if any(
        not any(execution < completion for execution in executions)
        for completion in completions
    ):
        raise AcceptanceFailure(
            f"Tool completion precedes its execution: {tool}"
        )
    return completions


def _has_later_model_step(
    trace: tuple[str, ...],
    last_tool_terminated: int,
    agent_completed: int,
) -> bool:
    for index in range(last_tool_terminated + 1, agent_completed - 3):
        match = re.fullmatch(
            r"model: step ([1-9][0-9]*) started",
            trace[index],
        )
        if match is None:
            continue
        step = match.group(1)
        expected = (
            f"model: step {step} started",
            "model: request",
            "model: response",
            f"model: step {step} completed",
        )
        if trace[index : index + 4] == expected:
            return True
    return False


def _run_unittest(workspace: Path) -> bool:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-v"],
        cwd=workspace,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        check=False,
    )
    return completed.returncode == 0


def _task(fixture: str, workspace: Path) -> str:
    return (
        f"{TASK_OBJECTIVES[fixture]} "
        f"Work only in Workspace {workspace}. "
        "Use str_replace_editor to view and modify the files. "
        "Use bash to run `python3 -m unittest discover -v`. "
        "Continue until all unittest tests pass. "
        "Keep the fix small and focused. Do not modify the test files."
    )


def _run_fixture(
    fixture: Path,
    api_key_file: Path,
    *,
    invoke_cli: InvokeCli = _invoke_cli,
    run_tests: RunTests = _run_unittest,
) -> AcceptanceResult:
    workspace = Path(
        tempfile.mkdtemp(prefix=f"nano-dsh-{fixture.name}-")
    ).resolve()
    trace: tuple[str, ...] = ()
    try:
        shutil.copytree(fixture, workspace, dirs_exist_ok=True)
        stdout, stderr = invoke_cli(
            [
                _task(fixture.name, workspace),
                "--workspace",
                str(workspace),
                "--api-key-file",
                str(api_key_file),
            ]
        )
        trace = _safe_trace(stderr)
        _assert_run(stdout, trace)
        if not run_tests(workspace):
            raise AcceptanceFailure("independent unittest verification failed")
    except CliInvocationFailure as error:
        return AcceptanceResult(
            fixture.name,
            workspace,
            False,
            str(error),
            error.trace,
        )
    except AcceptanceFailure as error:
        return AcceptanceResult(
            fixture.name,
            workspace,
            False,
            str(error),
            trace,
        )
    except Exception:
        return AcceptanceResult(
            fixture.name,
            workspace,
            False,
            "CLI/main flow raised an exception",
            trace,
        )

    shutil.rmtree(workspace)
    return AcceptanceResult(fixture.name, workspace, True, "passed", trace)


def _print_result(result: AcceptanceResult) -> None:
    if result.passed:
        print(f"{result.fixture}: PASS")
        return

    print(f"{result.fixture}: FAIL - {result.detail}")
    print(f"Workspace preserved: {result.workspace}")
    if result.trace:
        print("Sanitized Execution Trace:")
        for event in result.trace:
            print(f"  {event}")


def run_suite(
    api_key_file: Path,
    *,
    fixtures: Sequence[Path] = FIXTURES,
    invoke_cli: InvokeCli = _invoke_cli,
    run_tests: RunTests = _run_unittest,
) -> int:
    results = []
    for fixture in fixtures:
        result = _run_fixture(
            fixture,
            api_key_file,
            invoke_cli=invoke_cli,
            run_tests=run_tests,
        )
        results.append(result)
        _print_result(result)

    passed = sum(result.passed for result in results)
    print(f"Summary: {passed}/{len(results)} PASS")
    return 0 if passed == len(results) else 1


def main(argv: Sequence[str] | None = None) -> int:
    return run_suite(_parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
