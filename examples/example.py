"""Run three isolated nano-dsh Live Acceptance scenarios."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    ROOT / "examples/workspaces/logic-bug",
    ROOT / "examples/workspaces/boundary-bug",
    ROOT / "examples/workspaces/missing-implementation",
)
OBJECTIVES = {
    "logic-bug": "Correct the inventory availability calculation.",
    "boundary-bug": "Correct batch splitting at the end of the input.",
    "missing-implementation": "Implement the label formatting contract.",
}


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    workspace: Path
    cli_code: int
    test_code: int
    response: str
    trace: str
    passed: bool


RunProcess = Callable[
    [Sequence[str], Path],
    subprocess.CompletedProcess[str],
]


def _parse_args(argv: Sequence[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key-file", default=".key")
    return Path(parser.parse_args(argv).api_key_file).resolve()


def _run_process(
    command: Sequence[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _task(name: str, workspace: Path) -> str:
    return (
        f"{OBJECTIVES[name]} "
        f"Work only in Workspace {workspace}. "
        "Use str_replace_editor to inspect and edit files. "
        "Use bash to run `python -m unittest discover -v`. "
        "Continue until all tests pass. Do not modify tests."
    )


def _completed_agent_trace(stderr: str) -> bool:
    events = stderr.splitlines()
    tools = {
        "tool: complete str_replace_editor",
        "tool: complete bash",
    }
    if not tools <= set(events):
        return False
    last_tool = max(
        index
        for index, event in enumerate(events)
        if event in tools
    )
    later_steps = [
        index
        for index, event in enumerate(events)
        if index > last_tool
        and event.startswith("model: step ")
        and event.endswith(" started")
    ]
    return bool(later_steps) and "agent: run completed" in events[later_steps[0] :]


def _agent_trace(stderr: str) -> str:
    marker = "=== SYSTEM ==="
    start = stderr.find(marker)
    return stderr[start:].strip() if start >= 0 else ""


def _run_scenario(
    fixture: Path,
    api_key_file: Path,
    *,
    run_process: RunProcess = _run_process,
) -> ScenarioResult:
    workspace = Path(
        tempfile.mkdtemp(prefix=f"nano-dsh-{fixture.name}-")
    ).resolve()
    shutil.copytree(fixture, workspace, dirs_exist_ok=True)

    cli = run_process(
        (
            sys.executable,
            "-m",
            "nano_dsh",
            _task(fixture.name, workspace),
            "--workspace",
            str(workspace),
            "--api-key-file",
            str(api_key_file),
        ),
        ROOT,
    )
    tests = run_process(
        (sys.executable, "-m", "unittest", "discover", "-v"),
        workspace,
    )
    response = cli.stdout.strip()
    passed = (
        cli.returncode == 0
        and tests.returncode == 0
        and bool(response)
        and _completed_agent_trace(cli.stderr)
    )
    result = ScenarioResult(
        fixture.name,
        workspace,
        cli.returncode,
        tests.returncode,
        response,
        _agent_trace(cli.stderr) if cli.returncode == 0 else "",
        passed,
    )
    if passed:
        shutil.rmtree(workspace)
    return result


def _print_result(result: ScenarioResult) -> None:
    if result.trace:
        print(result.trace)
    elif result.response:
        print(f"  Response: {result.response}")
    print(f"{result.name}: {'PASS' if result.passed else 'FAIL'}")
    if not result.passed:
        print(
            f"  Exit codes: CLI={result.cli_code}, "
            f"unittest={result.test_code}"
        )
        print(f"  Workspace preserved: {result.workspace}")


def run_suite(
    api_key_file: Path,
    *,
    fixtures: Sequence[Path] = FIXTURES,
    run_process: RunProcess = _run_process,
) -> int:
    results = []
    for fixture in fixtures:
        result = _run_scenario(
            fixture,
            api_key_file,
            run_process=run_process,
        )
        results.append(result)
        _print_result(result)
    passed = sum(result.passed for result in results)
    print(f"Summary: {passed}/{len(results)} PASS")
    return 0 if passed == len(results) else 1


def main(argv: Sequence[str] | None = None) -> int:
    return run_suite(_parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
