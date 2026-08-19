import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "nano_dsh"


def _code_lines(path: Path) -> int:
    return sum(
        bool(line.strip()) and not line.lstrip().startswith("#")
        for line in path.read_text(encoding="utf-8").splitlines()
    )


class CodeSizeTests(unittest.TestCase):
    def test_production_code_stays_within_teaching_limits(self) -> None:
        counts = {
            path.relative_to(SOURCE_ROOT).as_posix(): _code_lines(path)
            for path in sorted(SOURCE_ROOT.rglob("*.py"))
        }
        total = sum(counts.values())
        oversized = {path: count for path, count in counts.items() if count > 200}
        details = ", ".join(f"{path}={count}" for path, count in oversized.items())
        message = f"total={total}; files over 200: {details or 'none'}"

        self.assertLessEqual(total, 1_000, message)
        self.assertFalse(oversized, message)


if __name__ == "__main__":
    unittest.main()
