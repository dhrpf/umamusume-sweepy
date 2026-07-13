#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = REPO_ROOT / "hermes-skills" / "mcp" / "sweepy-parent-builder" / "SKILL.md"


def _top_level_section(lines: list[str], name: str) -> tuple[int, int] | None:
    header = f"{name}:"
    for index, line in enumerate(lines):
        if line.rstrip("\n") == header:
            end = len(lines)
            for cursor in range(index + 1, len(lines)):
                stripped = lines[cursor].strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if not lines[cursor].startswith((" ", "\t")):
                    end = cursor
                    break
            return index, end
    return None


def _upsert_mcp_server(text: str, *, python_path: Path, server_path: Path, accounts_path: Path) -> str:
    lines = text.splitlines(keepends=True)
    section = _top_level_section(lines, "mcp_servers")
    block = [
        "  sweepy:\n",
        f"    command: {json.dumps(str(python_path))}\n",
        "    args:\n",
        f"      - {json.dumps(str(server_path))}\n",
        "    env:\n",
        f"      SWEEPY_ACCOUNTS_FILE: {json.dumps(str(accounts_path))}\n",
        "    enabled: true\n",
        "    supports_parallel_tool_calls: false\n",
        "    timeout: 300\n",
        "    connect_timeout: 60\n",
    ]

    if section is None:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend(["mcp_servers:\n", *block])
        return "".join(lines)

    start, end = section
    child_start = None
    child_end = None
    for index in range(start + 1, end):
        if lines[index].rstrip("\n") == "  sweepy:":
            child_start = index
            child_end = end
            for cursor in range(index + 1, end):
                stripped = lines[cursor].strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if lines[cursor].startswith("  ") and not lines[cursor].startswith("    "):
                    child_end = cursor
                    break
            break
    if child_start is not None:
        lines[child_start:child_end] = block
    else:
        lines[start + 1:start + 1] = block
    return "".join(lines)


def _enable_platform_toolset(text: str, platform: str, toolset: str) -> str:
    lines = text.splitlines(keepends=True)
    section = _top_level_section(lines, "platform_toolsets")
    if section is None:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend(
            [
                "platform_toolsets:\n",
                f"  {platform}:\n",
                f"    - {toolset}\n",
            ]
        )
        return "".join(lines)

    start, end = section
    platform_start = None
    platform_end = end
    for index in range(start + 1, end):
        if lines[index].rstrip("\n") == f"  {platform}:":
            platform_start = index
            for cursor in range(index + 1, end):
                stripped = lines[cursor].strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if lines[cursor].startswith("  ") and not lines[cursor].startswith("    "):
                    platform_end = cursor
                    break
            break
    if platform_start is None:
        lines[start + 1:start + 1] = [f"  {platform}:\n", f"    - {toolset}\n"]
        return "".join(lines)

    wanted = f"- {toolset}"
    if any(lines[index].strip() == wanted for index in range(platform_start + 1, platform_end)):
        return "".join(lines)
    lines[platform_end:platform_end] = [f"    - {toolset}\n"]
    return "".join(lines)


def render_config(
    text: str,
    *,
    python_path: Path,
    server_path: Path,
    accounts_path: Path,
) -> str:
    updated = _upsert_mcp_server(
        text,
        python_path=python_path,
        server_path=server_path,
        accounts_path=accounts_path,
    )
    updated = _enable_platform_toolset(updated, "cli", "sweepy")
    updated = _enable_platform_toolset(updated, "discord", "sweepy")
    return updated


def install(
    *,
    hermes_home: Path,
    config_path: Path,
    dry_run: bool = False,
) -> dict[str, str]:
    hermes_home = hermes_home.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    python_path = REPO_ROOT / "venv" / "bin" / "python"
    server_path = REPO_ROOT / "sweepy_mcp.py"
    accounts_path = REPO_ROOT / "accounts.json"
    destination_skill = (
        hermes_home / "skills" / "mcp" / "sweepy-parent-builder" / "SKILL.md"
    )

    missing = [path for path in (SOURCE_SKILL, python_path, server_path, accounts_path) if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required Sweepy files: " + ", ".join(map(str, missing)))

    current = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    updated = render_config(
        current,
        python_path=python_path,
        server_path=server_path,
        accounts_path=accounts_path,
    )
    backup_path = config_path.with_name(
        f"{config_path.name}.backup-sweepy-{int(time.time())}"
    )

    if not dry_run:
        destination_skill.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_SKILL, destination_skill)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists() and current != updated:
            shutil.copy2(config_path, backup_path)
        config_path.write_text(updated, encoding="utf-8")

    return {
        "skill": str(destination_skill),
        "config": str(config_path),
        "backup": str(backup_path) if current != updated else "",
        "changed": str(current != updated).lower(),
        "dry_run": str(bool(dry_run)).lower(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Sweepy MCP and Hermes skill")
    parser.add_argument(
        "--hermes-home",
        type=Path,
        default=Path.home() / ".hermes",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".hermes" / "config.yaml",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = install(
        hermes_home=args.hermes_home,
        config_path=args.config,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
