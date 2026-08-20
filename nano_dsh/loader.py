# Load ordered Plugin Specifications from TOML Profiles and Bundles.

import importlib
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .contracts import PluginSpec
from .cordis import Context


RawApply = Callable[[object, Mapping[str, object]], object]


@dataclass(frozen=True)
class Profile:
    # An ordered set of Bundle paths selected by one TOML file.
    bundles: tuple[Path, ...]


@dataclass(frozen=True)
class Bundle:
    # An ordered set of declarative Plugin Specifications.
    plugins: tuple[PluginSpec, ...]


def read_profile(path: Path) -> Profile:
    # Read a Profile and resolve Bundle paths from its directory.
    data = _read_toml(path)
    return Profile(tuple((path.parent / value).resolve() for value in data["bundles"]))


def read_bundle(path: Path) -> Bundle:
    # Read one Bundle and construct its Plugin Specifications.
    data = _read_toml(path)
    return Bundle(tuple(_plugin_spec(entry) for entry in data["plugins"]))


class Loader:
    # Turn Profile entries into dynamically imported Plugin Fibers.

    def __init__(self, context: Context) -> None:
        self._context = context

    def load(self, profile_path: Path) -> tuple[PluginSpec, ...]:
        # Register Plugins in Profile then Bundle entry order.
        loaded: list[PluginSpec] = []
        for bundle_path in read_profile(profile_path).bundles:
            for spec in read_bundle(bundle_path).plugins:
                fiber_apply = _bind_config(_load_apply(spec), spec.config)
                self._context.add_fiber(spec, fiber_apply)
                loaded.append(spec)
        return tuple(loaded)


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        return tomllib.load(source)


def _plugin_spec(entry: dict[str, Any]) -> PluginSpec:
    return PluginSpec(
        entry["id"],
        entry["module"],
        tuple(entry.get("inject", ())),
        entry.get("config", {}),
    )


def _load_apply(spec: PluginSpec) -> RawApply:
    module = importlib.import_module(spec.module)
    return cast(RawApply, module.apply)


def _bind_config(
    raw_apply: RawApply, config: Mapping[str, object]
) -> Callable[[object], object]:
    def fiber_apply(context: object) -> object:
        return raw_apply(context, config)

    return fiber_apply
