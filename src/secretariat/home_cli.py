"""Portable-home command wrapper with value-free lock/readiness status."""

from __future__ import annotations

import json

from . import cli as core_cli
from .backends import Tooling
from .config import DeviceConfigError, default_config_path, load_device_config
from .home_state import inspect_portable_home
from .kdbx_agent import KDBXAgentError


def main(arguments: list[str] | None = None) -> int:
    values = list(arguments or [])
    args = core_cli.parser().parse_args(values)
    if args.command != "home" or args.home_command != "status":
        return core_cli.main(values)
    try:
        config_path = default_config_path()
        config = load_device_config(config_path)
        status = inspect_portable_home(Tooling.detect(), config)
        report = {
            "config": "available" if config_path.is_file() else "default_or_environment",
            **status.as_dict(),
        }
        if args.json_output:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            for key, value in report.items():
                rendered = "none" if value is None else value
                print(f"{key}: {rendered}")
        return 0
    except (DeviceConfigError, KDBXAgentError) as error:
        if args.json_output:
            print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        else:
            print(f"secretariat: {error}", file=__import__("sys").stderr)
        return 2
