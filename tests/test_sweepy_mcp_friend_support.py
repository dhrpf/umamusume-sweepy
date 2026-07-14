from copy import deepcopy
import json

import httpx

import sweepy_mcp
from sweepy_jobs import SweepyJobStore


class FakeRegistry:
    def __init__(self, gateway):
        self.gateway = gateway

    def resolve(self, account=""):
        if account != "alpha":
            raise ValueError("Unknown account")
        return "alpha", self.gateway


class FriendGateway:
    def __init__(self):
        self.calls = []
        self.selection = {
            "deck": {
                "id": 4,
                "name": "Deck 4",
                "cards": [{"id": "30010", "name": "Fine Motion"}],
            },
            "trainee": {"id": "100601", "name": "Oguri Cap"},
            "friend": None,
            "veterans": [{"instance_id": 101}, {"instance_id": 202}],
            "preset": "parent-preset",
        }
        self.friends = [
            {
                "viewer_id": 111,
                "support_card_id": 30111,
                "support_name": "Super Creek",
                "type": "Stamina",
                "rarity": "SSR",
                "limit_break_count": 4,
                "exp": 100,
                "favorite_flag": 1,
                "friend_state": 2,
            }
        ]

    def request(self, method, path, payload=None):
        self.calls.append((method, path, deepcopy(payload)))
        if (method, path) == ("GET", "/api/session"):
            return {
                "success": True,
                "selection": deepcopy(self.selection),
                "friends": deepcopy(self.friends),
            }
        if (method, path) == ("POST", "/api/career/friends"):
            return {
                "success": True,
                "friends": deepcopy(self.friends),
                "source": "refresh" if (payload or {}).get("force_refresh") else "cache",
            }
        if (method, path) == ("POST", "/api/selection"):
            self.selection = deepcopy(payload["selection"])
            return {"success": True, "selection": deepcopy(self.selection)}
        return {"success": True}


def make_http_gateway():
    selection = {
        "deck": {
            "id": 4,
            "name": "Deck 4",
            "cards": [{"id": "30010", "name": "Fine Motion"}],
        },
        "trainee": {"id": "100601", "name": "Oguri Cap"},
        "friend": None,
        "veterans": [{"instance_id": 101}, {"instance_id": 202}],
        "preset": "parent-preset",
    }
    friend = {
        "viewer_id": 111,
        "support_card_id": 30111,
        "support_name": "Super Creek",
        "type": "Stamina",
        "rarity": "SSR",
        "limit_break_count": 4,
        "exp": 100,
        "favorite_flag": 1,
        "friend_state": 2,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal selection
        if request.method == "GET" and request.url.path == "/api/session":
            return httpx.Response(
                200,
                json={"success": True, "selection": deepcopy(selection), "friends": [friend]},
            )
        if request.method == "POST" and request.url.path == "/api/career/friends":
            return httpx.Response(
                200,
                json={"success": True, "friends": [friend], "source": "refresh"},
            )
        if request.method == "POST" and request.url.path == "/api/selection":
            payload = json.loads(request.content.decode("utf-8"))
            selection = deepcopy(payload["selection"])
            return httpx.Response(200, json={"success": True, "selection": selection})
        return httpx.Response(200, json={"success": True})

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )
    return sweepy_mcp.SweepyGateway(base_url="http://testserver", client=client)


def configure(monkeypatch, tmp_path, gateway):
    monkeypatch.setattr(sweepy_mcp, "account_registry", FakeRegistry(gateway))
    monkeypatch.setattr(
        sweepy_mcp,
        "job_store",
        SweepyJobStore(tmp_path / "control-plane.sqlite3"),
    )


def test_real_gateway_preserves_internal_viewer_id_for_friend_matching(monkeypatch, tmp_path):
    gateway = make_http_gateway()
    configure(monkeypatch, tmp_path, gateway)

    result = sweepy_mcp.find_friend_supports(
        account="alpha",
        name="Super Creek",
        support_type="Stamina",
        limit_break=4,
        force_refresh=True,
    )

    assert result["success"] is True
    assert result["match_count"] == 1
    assert result["recommended_candidate_id"].startswith("friend-")
    assert "viewer_id" not in result["matches"][0]


def test_real_gateway_can_select_and_verify_friend_without_leaking_viewer_id(monkeypatch, tmp_path):
    gateway = make_http_gateway()
    configure(monkeypatch, tmp_path, gateway)
    candidate = sweepy_mcp.find_friend_supports(
        account="alpha",
        name="Super Creek",
        support_type="Stamina",
        limit_break=4,
        force_refresh=True,
    )["recommended_candidate_id"]

    result = sweepy_mcp.select_friend_support(
        account="alpha",
        candidate_id=candidate,
        confirm=True,
        operation_id="discord-real-gateway-select",
    )

    assert result["success"] is True
    assert result["selection_verified"] is True
    assert result["selected_friend"]["support_name"] == "Super Creek"
    assert "viewer_id" not in result["selected_friend"]


def test_find_friend_supports_returns_opaque_deterministic_candidate(monkeypatch, tmp_path):
    gateway = FriendGateway()
    configure(monkeypatch, tmp_path, gateway)

    result = sweepy_mcp.find_friend_supports(
        account="alpha",
        name="Super Creek",
        support_type="Stamina",
        limit_break=4,
        force_refresh=True,
    )

    assert result["success"] is True
    assert result["match_count"] == 1
    assert result["requires_user_choice"] is False
    assert result["recommended_candidate_id"].startswith("friend-")
    assert "viewer_id" not in result["matches"][0]
    assert ("POST", "/api/career/friends", {"exclude_viewer_ids": [], "force_refresh": True}) in gateway.calls


def test_select_friend_support_requires_confirmation(monkeypatch, tmp_path):
    gateway = FriendGateway()
    configure(monkeypatch, tmp_path, gateway)
    candidate = sweepy_mcp.find_friend_supports(
        account="alpha",
        name="Super Creek",
        limit_break=4,
    )["recommended_candidate_id"]

    preview = sweepy_mcp.select_friend_support(
        account="alpha",
        candidate_id=candidate,
        confirm=False,
        operation_id="discord-select-friend",
    )

    assert preview["requires_confirmation"] is True
    assert preview["details"] == {
        "account": "alpha",
        "candidate_id": candidate,
    }
    assert gateway.selection["friend"] is None


def test_ensure_friend_support_selects_unique_query_match_atomically(monkeypatch, tmp_path):
    gateway = FriendGateway()
    configure(monkeypatch, tmp_path, gateway)

    result = sweepy_mcp.ensure_friend_support(
        account="alpha",
        name="Super Creek",
        support_type="Stamina",
        limit_break=4,
        confirm=True,
        operation_id="discord-ensure-friend",
    )

    assert result["success"] is True
    assert result["selection_verified"] is True
    assert result["selected_friend"]["support_name"] == "Super Creek"
    assert result["selected_friend"]["limit_break_count"] == 4
    assert gateway.selection["friend"]["support_card_id"] == 30111
    assert "viewer_id" not in result["selected_friend"]


def test_ensure_friend_support_requires_choice_for_multiple_card_variants(monkeypatch, tmp_path):
    gateway = FriendGateway()
    gateway.friends.append(
        {
            "viewer_id": 222,
            "support_card_id": 30222,
            "support_name": "Super Creek",
            "type": "Wisdom",
            "rarity": "SSR",
            "limit_break_count": 4,
            "exp": 100,
            "favorite_flag": 0,
            "friend_state": 1,
        }
    )
    configure(monkeypatch, tmp_path, gateway)

    result = sweepy_mcp.ensure_friend_support(
        account="alpha",
        name="Super Creek",
        limit_break=4,
        confirm=True,
        operation_id="discord-ensure-ambiguous",
    )

    assert result["success"] is False
    assert result["requires_user_choice"] is True
    assert result["unique_card_count"] == 2
    assert gateway.selection["friend"] is None


def test_select_friend_support_preserves_selection_and_verifies_readback(monkeypatch, tmp_path):
    gateway = FriendGateway()
    configure(monkeypatch, tmp_path, gateway)
    original = deepcopy(gateway.selection)
    candidate = sweepy_mcp.find_friend_supports(
        account="alpha",
        name="Super Creek",
        limit_break=4,
    )["recommended_candidate_id"]

    result = sweepy_mcp.select_friend_support(
        account="alpha",
        candidate_id=candidate,
        confirm=True,
        operation_id="discord-select-friend",
    )

    assert result["success"] is True
    assert result["selected_friend"] == {
        "candidate_id": candidate,
        "support_card_id": 30111,
        "support_name": "Super Creek",
        "type": "Stamina",
        "rarity": "SSR",
        "limit_break_count": 4,
        "exp": 100,
        "favorite": True,
        "following": True,
        "selectable": True,
        "conflicts": [],
    }
    assert gateway.selection["deck"] == original["deck"]
    assert gateway.selection["trainee"] == original["trainee"]
    assert gateway.selection["veterans"] == original["veterans"]
    assert gateway.selection["preset"] == original["preset"]
    assert gateway.selection["friend"]["viewer_id"] == 111

    selection_posts = [
        call for call in gateway.calls if call[:2] == ("POST", "/api/selection")
    ]
    assert len(selection_posts) == 1
    assert gateway.calls[-1][:2] == ("GET", "/api/session")
