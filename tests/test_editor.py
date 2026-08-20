from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nano_dsh.contracts import ToolOutput
from nano_dsh.plugins import editor


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


class EditorToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.ctx = FakeContext()
        editor.apply(self.ctx, {})
        self.definition = self.ctx.tools.definition
        self.handler = self.definition.handler

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def call(self, command: str, path: Path, **arguments) -> ToolOutput:
        return self.handler(
            {"command": command, "path": str(path), **arguments},
            self.workspace,
        )

    def test_schema_and_effect_registration(self) -> None:
        self.assertEqual(self.definition.name, "str_replace_editor")
        self.assertTrue(self.ctx.effect_used)
        self.assertEqual(
            set(self.definition.parameters["properties"]),
            {
                "command",
                "path",
                "file_text",
                "insert_line",
                "new_str",
                "old_str",
                "view_range",
            },
        )
        self.assertEqual(
            self.definition.parameters["required"],
            ["command", "path"],
        )
        self.assertFalse(self.definition.parameters["additionalProperties"])

    def test_plugin_config_is_trusted_after_loading(self) -> None:
        context = FakeContext()
        editor.apply(context, {"undo": True})
        self.assertEqual(context.tools.definition.name, "str_replace_editor")

    def test_view_file_with_line_numbers_and_range(self) -> None:
        target = self.workspace / "sample.txt"
        target.write_text("alpha\nbeta\ngamma\n")
        self.assertEqual(
            self.call("view", target).content,
            "1\talpha\n2\tbeta\n3\tgamma",
        )
        self.assertEqual(
            self.call("view", target, view_range=[2, -1]).content,
            "2\tbeta\n3\tgamma",
        )
        self.assertEqual(
            self.call("view", target, view_range=[2, 2]).content,
            "2\tbeta",
        )

    def test_view_directory_lists_immediate_children(self) -> None:
        (self.workspace / "a.txt").write_text("a")
        (self.workspace / "sub").mkdir()
        self.assertEqual(
            self.call("view", self.workspace).content,
            "a.txt\nsub/",
        )

    def test_create_writes_new_file_and_does_not_overwrite(self) -> None:
        target = self.workspace / "created.py"
        self.assertFalse(self.call("create", target, file_text="print('ok')\n").failed)
        self.assertEqual(target.read_text(), "print('ok')\n")
        result = self.call("create", target, file_text="changed")
        self.assertTrue(result.failed)
        self.assertIn("already exists", result.content)
        self.assertEqual(target.read_text(), "print('ok')\n")

    def test_str_replace_requires_one_literal_match(self) -> None:
        target = self.workspace / "replace.txt"
        target.write_text("before old after")
        self.assertFalse(self.call(
            "str_replace",
            target,
            old_str="old",
            new_str="new",
        ).failed)
        self.assertEqual(target.read_text(), "before new after")

        for content, old_str in (
            ("no match", "missing"),
            ("same same", "same"),
        ):
            target.write_text(content)
            with self.subTest(content=content):
                result = self.call(
                    "str_replace",
                    target,
                    old_str=old_str,
                    new_str="replacement",
                )
                self.assertTrue(result.failed)
                self.assertEqual(target.read_text(), content)

    def test_insert_supports_start_middle_and_end(self) -> None:
        target = self.workspace / "insert.txt"
        target.write_text("a\nb")
        self.assertFalse(self.call("insert", target, insert_line=1, new_str="x\ny").failed)
        self.assertEqual(target.read_text(), "a\nx\ny\nb")

        start = self.workspace / "start.txt"
        start.write_text("b")
        self.assertFalse(self.call("insert", start, insert_line=0, new_str="a").failed)
        self.assertEqual(start.read_text(), "a\nb")

        end = self.workspace / "end.txt"
        end.write_text("a\n")
        self.assertFalse(self.call("insert", end, insert_line=1, new_str="b").failed)
        self.assertEqual(end.read_text(), "a\nb")

    def test_insert_rejects_invalid_position_and_empty_text(self) -> None:
        target = self.workspace / "invalid-insert.txt"
        target.write_text("one\n")
        invalid = (
            {"insert_line": -1, "new_str": "x"},
            {"insert_line": 2, "new_str": "x"},
            {"insert_line": True, "new_str": "x"},
            {"insert_line": 0, "new_str": ""},
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                self.assertTrue(self.call("insert", target, **arguments).failed)
                self.assertEqual(target.read_text(), "one\n")

    def test_rejects_relative_outside_and_symlink_escape_paths(self) -> None:
        relative = self.handler(
            {"command": "view", "path": "relative.txt"},
            self.workspace,
        )
        self.assertEqual(relative, ToolOutput("Error: path must be absolute", True))

        outside_temp = tempfile.TemporaryDirectory()
        self.addCleanup(outside_temp.cleanup)
        outside_root = Path(outside_temp.name)
        outside = outside_root / "outside.txt"
        outside.write_text("secret")
        self.assertTrue(self.call("view", outside).failed)

        link = self.workspace / "link.txt"
        link.symlink_to(outside)
        self.assertTrue(self.call("view", link).failed)

        outside_dir = outside_root / "outside-dir"
        outside_dir.mkdir()
        parent_link = self.workspace / "linked-dir"
        parent_link.symlink_to(outside_dir, target_is_directory=True)
        self.assertTrue(self.call(
            "create",
            parent_link / "new.txt",
            file_text="escape",
        ).failed)
        self.assertFalse((outside_dir / "new.txt").exists())

    def test_rejects_nul_path_without_exposing_input(self) -> None:
        nul_path = f"{self.workspace}/private\x00suffix"
        result = self.handler(
            {"command": "view", "path": nul_path},
            self.workspace,
        )
        self.assertTrue(result.failed)
        self.assertNotIn("private", result.content)

    def test_invalid_arguments_and_range_fail(self) -> None:
        target = self.workspace / "range.txt"
        target.write_text("one\ntwo")
        invalid = (
            None,
            {"command": "delete", "path": str(target)},
            {"command": "view", "path": str(target), "extra": True},
            {
                "command": "view",
                "path": str(target),
                "view_range": [0, 1],
            },
            {
                "command": "view",
                "path": str(target),
                "view_range": [1, 3],
            },
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                self.assertTrue(self.handler(arguments, self.workspace).failed)

    def test_view_output_is_truncated(self) -> None:
        target = self.workspace / "large.txt"
        target.write_text("x" * 17_000)
        result = self.call("view", target)
        self.assertEqual(len(result.content), 16_000)


if __name__ == "__main__":
    unittest.main()
