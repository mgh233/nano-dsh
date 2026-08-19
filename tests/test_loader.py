from __future__ import annotations

import sys
import tempfile
import types
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from nano_dsh.contracts import PluginSpec, RunFailure
from nano_dsh.loader import Loader, read_bundle, read_profile


class FakeContext:
    def __init__(self) -> None:
        self.calls: list[tuple[PluginSpec, Callable[[object], object]]] = []
        self.applied: list[object] = []

    def add_fiber(
        self,
        spec: PluginSpec,
        apply: Callable[[object], object],
    ) -> None:
        self.calls.append((spec, apply))
        apply(self)


class LoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.modules: list[str] = []

    def tearDown(self) -> None:
        for name in self.modules:
            sys.modules.pop(name, None)
        self.directory.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def module(self, name: str) -> types.ModuleType:
        module = types.ModuleType(name)
        module.apply = lambda context, config: None
        self.modules.append(name)
        sys.modules[name] = module
        return module

    def test_loads_two_ordered_bundles_and_calls_module_apply(self) -> None:
        first = self.module("test_loader_first")
        second = self.module("test_loader_second")
        first.apply = lambda context, config: context.applied.append(config)
        second.apply = lambda context, config: context.applied.append(config)
        profile = self.write("profiles/main.toml", 'bundles = ["../bundles/base.toml", "../bundles/headless.toml"]')
        self.write("bundles/base.toml", '[[plugins]]\nid = "consumer"\nmodule = "test_loader_first"\ninject = ["providers"]\n[plugins.config]\nkey = "one"')
        self.write("bundles/headless.toml", '[[plugins]]\nid = "provider"\nmodule = "test_loader_second"')
        context = FakeContext()

        loaded = Loader(context).load(profile)

        self.assertEqual([spec.id for spec in loaded], ["consumer", "provider"])
        self.assertEqual([spec.id for spec, _ in context.calls], ["consumer", "provider"])
        self.assertIsNot(context.calls[0][1], first.apply)
        self.assertIsNot(context.calls[1][1], second.apply)
        self.assertEqual(context.calls[0][0].config, {"key": "one"})
        self.assertEqual(context.applied, [{"key": "one"}, {}])
        self.assertIs(context.applied[0], context.calls[0][0].config)
        self.assertIs(context.applied[1], context.calls[1][0].config)

    def test_resolves_bundle_paths_relative_to_profile(self) -> None:
        profile = self.write("profiles/main.toml", 'bundles = ["../bundles/base.toml"]')

        result = read_profile(profile)

        self.assertEqual(result.bundles, ((self.root / "bundles/base.toml").resolve(),))

    def test_profile_reports_first_bundle_resolution_error(self) -> None:
        profile = self.write("profiles/main.toml", 'bundles = ["loop", 1]')
        (profile.parent / "loop").symlink_to("loop")

        with self.assertRaises(RuntimeError):
            read_profile(profile)

    def test_consumer_before_provider_is_not_sorted(self) -> None:
        self.module("test_loader_consumer")
        self.module("test_loader_provider")
        profile = self.write("profile.toml", 'bundles = ["bundle.toml"]')
        self.write("bundle.toml", '[[plugins]]\nid = "consumer"\nmodule = "test_loader_consumer"\ninject = ["service"]\n\n[[plugins]]\nid = "provider"\nmodule = "test_loader_provider"')
        context = FakeContext()

        Loader(context).load(profile)

        self.assertEqual([spec.id for spec, _ in context.calls], ["consumer", "provider"])

    def test_rejects_invalid_profile_and_bundle_values(self) -> None:
        cases = [
            ("profile.toml", 'bundles = "bundle.toml"', read_profile),
            ("profile.toml", 'bundles = [1]', read_profile),
            ("bundle.toml", 'plugins = "not-a-list"', read_bundle),
            ("bundle.toml", 'plugins = ["not-a-table"]', read_bundle),
            ("bundle.toml", '[[plugins]]\nid = ""\nmodule = "mod"', read_bundle),
            ("bundle.toml", '[[plugins]]\nid = 1\nmodule = "mod"', read_bundle),
            ("bundle.toml", '[[plugins]]\nid = "x"\nmodule = ""', read_bundle),
            ("bundle.toml", '[[plugins]]\nid = "x"\nmodule = 1', read_bundle),
            ("bundle.toml", '[[plugins]]\nid = "x"\nmodule = "mod"\ninject = [1]', read_bundle),
            ("bundle.toml", '[[plugins]]\nid = "x"\nmodule = "mod"\nconfig = "bad"', read_bundle),
        ]
        for relative, content, reader in cases:
            with self.subTest(content=content):
                path = self.write(relative, content)
                with self.assertRaises(RunFailure):
                    reader(path)

    def test_reports_first_invalid_plugin_entry(self) -> None:
        path = self.write(
            "mixed-invalid-bundle.toml",
            'plugins = [{ id = "", module = "mod" }, "not-a-table"]',
        )

        with self.assertRaisesRegex(RunFailure, "empty Plugin id"):
            read_bundle(path)

    def test_rejects_missing_files_duplicate_ids_and_invalid_apply(self) -> None:
        with self.assertRaises(RunFailure):
            read_profile(self.root / "missing.toml")
        missing_bundle = self.write("missing-bundle.toml", 'bundles = ["not-here.toml"]')
        with self.assertRaises(RunFailure):
            Loader(FakeContext()).load(missing_bundle)
        self.module("test_loader_good")
        profile = self.write("profile.toml", 'bundles = ["bundle.toml"]')
        self.write("bundle.toml", '[[plugins]]\nid = "same"\nmodule = "test_loader_good"\n\n[[plugins]]\nid = "same"\nmodule = "test_loader_good"')
        with self.assertRaises(RunFailure):
            Loader(FakeContext()).load(profile)
        self.write("bundle.toml", '[[plugins]]\nid = "bad"\nmodule = "test_loader_bad"')
        sys.modules["test_loader_bad"] = types.ModuleType("test_loader_bad")
        self.modules.append("test_loader_bad")
        with self.assertRaises(RunFailure):
            Loader(FakeContext()).load(profile)

    def test_rejects_malformed_toml(self) -> None:
        path = self.write("profile.toml", "bundles = [")
        with self.assertRaises(RunFailure):
            read_profile(path)

    def test_rejects_missing_module(self) -> None:
        profile = self.write("profile.toml", 'bundles = ["bundle.toml"]')
        self.write("bundle.toml", '[[plugins]]\nid = "missing"\nmodule = "does_not_exist_for_nano_dsh"')
        with patch("nano_dsh.loader.importlib.import_module", side_effect=ImportError):
            with self.assertRaises(RunFailure):
                Loader(FakeContext()).load(profile)


if __name__ == "__main__":
    unittest.main()
