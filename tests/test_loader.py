from __future__ import annotations

import sys
import tempfile
import types
import unittest
from collections.abc import Callable
from pathlib import Path

from nano_dsh.contracts import PluginSpec
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

    def test_consumer_before_provider_is_not_sorted(self) -> None:
        self.module("test_loader_consumer")
        self.module("test_loader_provider")
        profile = self.write("profile.toml", 'bundles = ["bundle.toml"]')
        self.write("bundle.toml", '[[plugins]]\nid = "consumer"\nmodule = "test_loader_consumer"\ninject = ["service"]\n\n[[plugins]]\nid = "provider"\nmodule = "test_loader_provider"')
        context = FakeContext()

        Loader(context).load(profile)

        self.assertEqual([spec.id for spec, _ in context.calls], ["consumer", "provider"])

if __name__ == "__main__":
    unittest.main()
