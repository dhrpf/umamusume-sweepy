from pathlib import Path

from scripts.install_hermes_sweepy import install, render_config


BASE_CONFIG = """model: test
platform_toolsets:
  cli:
    - browser
  discord:
    - messaging
mcp_servers:
  existing:
    command: existing-mcp
    enabled: true
"""


def test_render_config_adds_stdio_server_and_platform_toolsets(tmp_path):
    rendered = render_config(
        BASE_CONFIG,
        python_path=Path("/repo/venv/bin/python"),
        server_path=Path("/repo/sweepy_mcp.py"),
        accounts_path=Path("/repo/accounts.json"),
    )

    assert "  sweepy:\n" in rendered
    assert '    command: "/repo/venv/bin/python"\n' in rendered
    assert '      - "/repo/sweepy_mcp.py"\n' in rendered
    assert '      SWEEPY_ACCOUNTS_FILE: "/repo/accounts.json"\n' in rendered
    assert "    supports_parallel_tool_calls: false\n" in rendered
    assert rendered.count("    - sweepy\n") == 2
    assert "  existing:\n" in rendered


def test_render_config_is_idempotent_and_replaces_existing_sweepy_block():
    first = render_config(
        BASE_CONFIG,
        python_path=Path("/old/python"),
        server_path=Path("/old/server.py"),
        accounts_path=Path("/old/accounts.json"),
    )
    second = render_config(
        first,
        python_path=Path("/new/python"),
        server_path=Path("/new/server.py"),
        accounts_path=Path("/new/accounts.json"),
    )
    third = render_config(
        second,
        python_path=Path("/new/python"),
        server_path=Path("/new/server.py"),
        accounts_path=Path("/new/accounts.json"),
    )

    assert second == third
    assert second.count("  sweepy:\n") == 1
    assert "/old/python" not in second
    assert '    command: "/new/python"' in second
    assert second.count("    - sweepy\n") == 2


def test_install_copies_skill_updates_config_and_creates_backup(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    config = hermes_home / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(BASE_CONFIG, encoding="utf-8")

    result = install(hermes_home=hermes_home, config_path=config)

    skill = hermes_home / "skills" / "mcp" / "sweepy-parent-builder" / "SKILL.md"
    assert skill.exists()
    assert skill.read_text(encoding="utf-8").startswith("---\nname: sweepy-parent-builder")
    assert "  sweepy:\n" in config.read_text(encoding="utf-8")
    assert result["changed"] == "true"
    assert Path(result["backup"]).exists()


def test_skill_frontmatter_and_required_workflow_tools_are_present():
    skill = (
        Path(__file__).resolve().parents[1]
        / "hermes-skills"
        / "mcp"
        / "sweepy-parent-builder"
        / "SKILL.md"
    )
    content = skill.read_text(encoding="utf-8")

    assert content.startswith("---\n")
    assert "name: sweepy-parent-builder" in content[:1000]
    assert "description: Use when" in content[:1200]
    assert len(content) <= 100_000
    for tool_name in (
        "list_accounts",
        "get_cached_account_snapshot",
        "scan_cached_legacy_loops",
        "preview_shared_g1_agenda",
        "launch_bot",
        "preview_parent_campaign",
        "create_parent_campaign",
        "start_parent_campaign",
        "prepare_parent_campaign_run",
        "run_parent_campaign_career",
        "collect_parent_campaign_result",
        "list_parent_candidates",
    ):
        assert tool_name in content
