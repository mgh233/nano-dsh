# Load ordered Plugin Specifications from TOML Profiles and Bundles.

import importlib
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .contracts import PluginSpec, RunFailure


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
    data = _read_toml(path, "Profile")
    bundles = data.get("bundles")
    if not isinstance(bundles, list):
        raise RunFailure(f"Profile {path} must contain a bundles array")
    resolved: list[Path] = []
    for value in bundles:
        if not isinstance(value, str) or not value.strip():
            raise RunFailure(f"Profile {path} has an invalid Bundle path")
        resolved.append((path.parent / value).resolve())
    return Profile(tuple(resolved))


def read_bundle(path: Path) -> Bundle:
    # Read one Bundle and validate each Plugin Specification.
    data = _read_toml(path, "Bundle")
    entries = data.get("plugins")
    if not isinstance(entries, list):
        raise RunFailure(f"Bundle {path} must contain a plugins array")
    plugins: list[PluginSpec] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RunFailure(f"Bundle {path} has a non-table Plugin entry")
        plugins.append(_plugin_spec(path, entry))
    return Bundle(tuple(plugins))


class Loader:
    # Turn Profile entries into dynamically imported Plugin Fibers.

    def __init__(self, context: object) -> None:
        self._context = context

    def load(self, profile_path: Path) -> tuple[PluginSpec, ...]:
        # Register Plugins in Profile then Bundle entry order.
        seen: set[str] = set()
        loaded: list[PluginSpec] = []
        for bundle_path in read_profile(profile_path).bundles:
            for spec in read_bundle(bundle_path).plugins:
                if spec.id in seen:
                    raise RunFailure(f"Duplicate Plugin id: {spec.id}")
                seen.add(spec.id)
                fiber_apply = _bind_config(_load_apply(spec), spec.config)
                self._context.add_fiber(spec, fiber_apply)  # type: ignore[attr-defined]
                loaded.append(spec)
        return tuple(loaded)


def _read_toml(path: Path, kind: str) -> dict[str, Any]:
    try:
        with path.open("rb") as source:
            data = tomllib.load(source)
    except FileNotFoundError as error:
        raise RunFailure(f"{kind} file does not exist: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise RunFailure(f"Malformed {kind} TOML: {path}") from error
    return data


def _plugin_spec(path: Path, entry: dict[str, Any]) -> PluginSpec:
    plugin_id = entry.get("id")
    module = entry.get("module")
    inject = entry.get("inject", [])
    config = entry.get("config", {})
    if not isinstance(plugin_id, str) or not plugin_id.strip():
        raise RunFailure(f"Bundle {path} has an empty Plugin id")
    if not isinstance(module, str) or not module.strip():
        raise RunFailure(f"Bundle {path} has an empty Plugin module")
    if not isinstance(inject, list) or not all(isinstance(name, str) for name in inject):
        raise RunFailure(f"Plugin {plugin_id} has invalid inject Services")
    if not isinstance(config, dict):
        raise RunFailure(f"Plugin {plugin_id} config must be a table")
    return PluginSpec(plugin_id, module, tuple(inject), config)


def _load_apply(spec: PluginSpec) -> RawApply:
    try:
        module = importlib.import_module(spec.module)
    except ImportError as error:
        raise RunFailure(f"Cannot import Plugin {spec.id}: {spec.module}") from error
    apply = getattr(module, "apply", None)
    if not callable(apply):
        raise RunFailure(f"Plugin {spec.id} has no callable apply(ctx, config)")
    return cast(RawApply, apply)


def _bind_config(
    raw_apply: RawApply, config: Mapping[str, object]
) -> Callable[[object], object]:
    def fiber_apply(context: object) -> object:
        return raw_apply(context, config)

    return fiber_apply
