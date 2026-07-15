import asyncio
from pathlib import Path

import main


ROOT = Path(__file__).resolve().parent.parent


class FakeDeckClient:
    def __init__(self):
        self.payloads = []

    def change_support_card_deck_party(self, support_card_deck_array):
        self.payloads.append(support_card_deck_array)
        return {"data_headers": {"result_code": 1}, "data": {}}


class IdleDailies:
    running = False


class IdleCareerRunner:
    def snapshot(self):
        return {"running": False}


def raw_decks():
    return [
        {
            "deck_id": deck_id,
            "name": f"Deck {deck_id}",
            "support_card_id_array": [deck_id * 100 + slot for slot in range(1, 6)],
        }
        for deck_id in range(1, 11)
    ]


def test_update_support_deck_saves_full_ten_deck_party_and_updates_dashboard(monkeypatch):
    client = FakeDeckClient()
    decks = raw_decks()
    monkeypatch.setattr(main, "active_client", client)
    monkeypatch.setattr(main, "active_support_card_deck_array", decks)
    monkeypatch.setattr(
        main,
        "active_dashboard_data",
        {
            "decks": [],
            "supports": [
                {"id": "30001", "limit_break_count": 4},
                {"id": "30002", "limit_break_count": 3},
                {"id": "30003", "limit_break_count": 2},
            ],
        },
    )
    monkeypatch.setattr(main, "dailies_runner", IdleDailies())
    monkeypatch.setattr(main, "career_runner", IdleCareerRunner())
    monkeypatch.setattr(
        main,
        "support_map",
        {
            "30001": {"name": "Speed One", "type": "Speed", "rarity": "SSR"},
            "30002": {"name": "Speed Two", "type": "Speed", "rarity": "SSR"},
            "30003": {"name": "Wit One", "type": "Wisdom", "rarity": "SR"},
        },
    )

    result = asyncio.run(
        main.update_support_deck(
            main.SupportDeckUpdateRequest(
                deck_id=3,
                name="Trackblazer Speed",
                support_card_ids=[30001, 30002, 30003],
            )
        )
    )

    assert result["success"] is True
    assert len(client.payloads) == 1
    sent = client.payloads[0]
    assert len(sent) == 10
    assert sent[0] == decks[0]
    assert sent[1] == decks[1]
    assert sent[2] == {
        "deck_id": 3,
        "name": "Trackblazer Speed",
        "support_card_id_array": [30001, 30002, 30003, 0, 0],
    }
    assert sent[3:] == decks[3:]
    assert main.active_support_card_deck_array == sent

    dashboard_deck = next(deck for deck in main.active_dashboard_data["decks"] if deck["id"] == 3)
    assert dashboard_deck["name"] == "Trackblazer Speed"
    assert [card["id"] for card in dashboard_deck["cards"]] == ["30001", "30002", "30003"]
    assert dashboard_deck["cards"][2]["type"] == "Wit"


def test_support_deck_editor_frontend_contract():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8")

    for element_id in (
        "deck-editor-modal",
        "deck-editor-name",
        "deck-editor-slots",
        "deck-editor-search",
        "deck-editor-type-filter",
        "deck-editor-owned",
        "deck-editor-save",
        "deck-editor-cancel",
    ):
        assert f'id="{element_id}"' in index_html

    assert "deck-edit-btn" in app_js
    assert "data-deck-id" in app_js
    assert "deck-incomplete" in app_js
    assert "renderDecks(dashData.decks)" in app_js
    assert "openDeckEditor" in app_js
    assert "renderDeckEditor" in app_js
    assert "support_card_ids" in app_js
    assert "'/api/support-decks/update'" in app_js
