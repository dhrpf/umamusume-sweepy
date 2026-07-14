import asyncio
import json
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parent.parent


def test_stdio_protocol_discovers_lifecycle_tools_and_confirmation_preview(tmp_path):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(
        json.dumps([{"name": "alpha", "port": 19161, "enabled": True}]),
        encoding="utf-8",
    )

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "sweepy_mcp.py")],
            cwd=ROOT,
            env={
                "SWEEPY_ACCOUNTS_FILE": str(accounts),
                "SWEEPY_JOBS_DB": str(tmp_path / "control-plane.sqlite3"),
                "SWEEPY_CAMPAIGNS_DB": str(tmp_path / "campaigns.sqlite3"),
            },
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {
                    "list_accounts",
                    "get_account_runtime",
                    "get_bot_logs",
                    "launch_bot",
                    "stop_bot",
                    "restart_bot",
                    "wait_until_ready",
                    "get_recent_operations",
                    "find_friend_supports",
                    "ensure_friend_support",
                    "select_friend_support",
                } <= names

                tools_by_name = {tool.name: tool for tool in tools.tools}
                campaign_schema = tools_by_name["create_parent_campaign"].inputSchema
                spec_schema = campaign_schema["$defs"]["ParentCampaignSpec"]
                assert {"trainee", "deck"} <= set(spec_schema["properties"])
                assert campaign_schema["$defs"]["TraineeSelectionMode"]["enum"] == [
                    "current",
                    "named",
                    "auto",
                ]
                assert campaign_schema["$defs"]["DeckSelectionMode"]["enum"] == [
                    "current",
                    "named",
                    "auto",
                ]
                assert campaign_schema["$defs"]["TraineeSelectionPolicy"]["properties"][
                    "objective"
                ]["enum"] == ["best_score", "highest_affinity"]

                for tool_name in (
                    "launch_bot",
                    "stop_bot",
                    "restart_bot",
                    "run_dailies",
                    "stop_dailies",
                    "run_career",
                    "stop_career",
                    "refill_tp",
                    "set_turn_delay",
                    "create_parent_campaign",
                    "start_parent_campaign",
                    "advance_parent_campaign",
                    "pause_parent_campaign",
                    "resume_parent_campaign",
                    "cancel_parent_campaign",
                    "select_parent_candidate",
                    "ensure_friend_support",
                    "select_friend_support",
                    "prepare_parent_campaign_run",
                    "run_parent_campaign_career",
                    "collect_parent_campaign_result",
                ):
                    assert "operation_id" in tools_by_name[tool_name].inputSchema["properties"]

                preview = await session.call_tool(
                    "launch_bot",
                    {"account": "alpha", "confirm": False},
                )
                assert preview.isError is False
                content = preview.structuredContent
                assert content["success"] is False
                assert content["requires_confirmation"] is True
                assert content["operation_id"]
                assert content["action"] == "launch_bot"
                assert content["details"] == {"account": "alpha"}
                assert content["instruction"] == (
                    "Call the same tool again with confirm=true after user approval."
                )

    asyncio.run(run())
