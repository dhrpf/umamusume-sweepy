import os
import json
import re
import subprocess
import sys
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pathlib import Path
import random
import time
import threading
from copy import deepcopy
import frida
from account_snapshot import save_load_index_snapshot
from career_bot import master_data
from career_bot import affinity as affinity_calc
from career_bot import advisor
from career_bot import aptitude
from career_bot.dailies import DailiesRunner
from career_bot.independent_training.finalizer import IndependentFinalizer
from career_bot.independent_training.models import (
    EnqueueRuns,
    IndependentTrainingPreset,
)
from career_bot.independent_training.races import (
    canonicalize_start_race_array,
)
from career_bot.independent_training.runner import IndependentTrainingRunner
from career_bot.independent_training.service import IndependentTrainingService, WorkflowConflict
from career_bot.independent_training.store import (
    IndependentTrainingStore,
    InvalidRunTransition,
    PresetNotFound,
    RunNotFound,
    RunVersionConflict,
)
from career_bot.independent_training.tp_cost import (
    resolve_independent_training_tp_cost,
)
from career_bot.objectives import CareerObjectiveResolver
from career_bot.presets import PresetStore, PresetStoreError
from career_bot.runner import CareerRunner
from career_bot.campaigns.factor_semantics import (
    direct_lineage_spark_totals,
    self_spark_totals,
)
from career_bot.campaigns.friend_support import find_trainee_deck_conflicts
from career_bot.campaigns.models import CampaignSparkTarget, ParentCampaignSpec
from career_bot.campaigns.planner import CampaignPlanner
from career_bot.campaigns.runner import CampaignRunner
from career_bot.campaigns.service import CampaignService
from career_bot.campaigns.store import CampaignError, CampaignNotFound, CampaignStore, InvalidTransition
from sweepy_jobs import SweepyJobStore
from uma_api.client import UmaClient, runtime_output_root
from career_bot.delay import (
    GateKeeper, dna_sleep, dna_uniform,
    decide_tp_action, pick_delay_seconds, compute_regen_wait_seconds,
)

PROCESS_NAME = os.environ.get("UMA_PROCESS_NAME", "UmamusumePrettyDerby.exe")
APP_ID = "3224770"

JS_CODE = r'''
'use strict';
(function() {
    var buffers = {};
    var attached = {};
    function hex2(n) { return ('0' + (n & 255).toString(16)).slice(-2); }
    function uuidFromHex(h) {
        return h.substring(0, 8) + '-' + h.substring(8, 12) + '-' + h.substring(12, 16) + '-' + h.substring(16, 20) + '-' + h.substring(20);
    }
    function b64(s) {
        var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
        var out = [];
        var buffer = 0;
        var bits = 0;
        for (var i = 0; i < s.length; i++) {
            var c = s.charAt(i);
            if (c === '=') break;
            var idx = chars.indexOf(c);
            if (idx < 0) continue;
            buffer = (buffer << 6) | idx;
            bits += 6;
            if (bits >= 8) {
                bits -= 8;
                out.push((buffer >> bits) & 255);
            }
        }
        return out;
    }
    function parseWire(endpoint, viewerId, body, appVer, resVer) {
        var decoded = b64(body);
        if (decoded.length < 140) return;
        var headerLen = decoded[0] | (decoded[1] << 8) | (decoded[2] << 16) | (decoded[3] << 24);
        var blob1End = 4 + headerLen;
        if (headerLen < 120 || headerLen > 2048 || decoded.length < blob1End) return;
        
        var udidHex = '';
        for (var i = blob1End - 96; i < blob1End - 80; i++) udidHex += hex2(decoded[i]);
        var authHex = '';
        for (var j = blob1End - 48; j < blob1End; j++) authHex += hex2(decoded[j]);
        
        if (!viewerId || !authHex || authHex.length < 64 || udidHex.length !== 32) return;
        
        send({
            type: 'creds',
            endpoint: endpoint,
            viewer_id: parseInt(viewerId, 10),
            udid: uuidFromHex(udidHex),
            auth_key: authHex,
            auth_key_len: authHex.length / 2,
            app_ver: appVer,
            res_ver: resVer,
            body: body
        });
    }
    function parseHttp(text) {
        if (text.indexOf('/umamusume/') < 0) return;
        var em = text.match(/POST\s+\/umamusume\/([^\s]+)\s+HTTP/i);
        var vm = text.match(/(?:^|\r\n)(?:ViewerID|ViewerId):\s*(\d+)/i);
        var appVer = text.match(/(?:^|\r\n)APP-VER:\s*([^\r\n]+)/i);
        var resVer = text.match(/(?:^|\r\n)RES-VER:\s*([^\r\n]+)/i);
        var idx = text.indexOf('\r\n\r\n');
        if (!em || !vm || idx < 0) return;
        parseWire(em[1], vm[1], text.substring(idx + 4), appVer ? appVer[1].trim() : '', resVer ? resVer[1].trim() : '');
    }
    function parseChunk(key, chunk) {
        var buf = (buffers[key] || '') + chunk;
        if (buf.length > 2097152) buf = buf.substring(buf.length - 1048576);
        var start = buf.indexOf('POST ');
        if (start < 0) {
            buffers[key] = buf.slice(-4096);
            return;
        }
        if (start > 0) buf = buf.substring(start);
        var headerEnd = buf.indexOf('\r\n\r\n');
        if (headerEnd < 0) {
            buffers[key] = buf;
            return;
        }
        var headers = buf.substring(0, headerEnd);
        var lm = headers.match(/Content-Length:\s*(\d+)/i);
        var length = lm ? parseInt(lm[1], 10) : 0;
        var total = headerEnd + 4 + length;
        if (length > 0 && buf.length < total) {
            buffers[key] = buf;
            return;
        }
        parseHttp(length > 0 ? buf.substring(0, total) : buf);
        buffers[key] = buf.length > total ? buf.substring(total) : '';
    }
    function hookTls() {
        var ga = Process.findModuleByName('GameAssembly.dll');
        if (!ga) return false;
        var installFn = ga.findExportByName('il2cpp_unity_install_unitytls_interface');
        if (!installFn) return false;
        var rb = new Uint8Array(installFn.readByteArray(16));
        var realFn = installFn;
        if (rb[0] === 0xe9) {
            var off = rb[1] | (rb[2] << 8) | (rb[3] << 16) | (rb[4] << 24);
            if (off > 0x7fffffff) off -= 0x100000000;
            realFn = installFn.add(5 + off);
            rb = new Uint8Array(realFn.readByteArray(16));
        }
        var globalPtr = null;
        if (rb[0] === 0x48 && rb[1] === 0x89 && rb[2] === 0x0d) {
            var disp = rb[3] | (rb[4] << 8) | (rb[5] << 16) | (rb[6] << 24);
            if (disp > 0x7fffffff) disp -= 0x100000000;
            globalPtr = realFn.add(7 + disp);
        }
        if (!globalPtr) return false;
        var iface = globalPtr.readPointer();
        if (!iface || iface.isNull()) return false;
        var hookedTls = 0;
        [0xe0, 0xe8].forEach(function(off) {
            var addr = iface.add(off).readPointer();
            if (!addr || addr.isNull()) return;
            var key = 'tls_' + addr.toString();
            if (attached[key]) return;
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        var len = args[2].toInt32();
                        if (len <= 0 || len > 1048576 || args[1].isNull()) return;
                        try {
                            var bytes = args[1].readByteArray(len);
                            var u8 = new Uint8Array(bytes);
                            var s = '';
                            for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                            parseChunk(args[0].toString(), s);
                        } catch (e) {}
                    }
                });
                attached[key] = true;
                hookedTls++;
            } catch (e) {}
        });
        return hookedTls > 0;
    }
    var tlsDone = false;
    var timer = setInterval(function() {
        try {
            if (!tlsDone) tlsDone = hookTls();
            if (tlsDone) clearInterval(timer);
        } catch (e) {}
    }, 1000);
})();
'''


DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", 1616))

AUTH_CACHE_PATH = runtime_output_root() / 'auth_cache.json'

def save_auth_cache(cfg):
    try:
        AUTH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        safe = {k: v for k, v in cfg.items() if k not in ('steam_session_ticket',)}
        with open(AUTH_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(safe, f)
    except Exception as e:
        print(f'[auth cache] save failed: {e}', flush=True)

def load_auth_cache():
    try:
        if not AUTH_CACHE_PATH.exists():
            return None
        with open(AUTH_CACHE_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        if has_fresh_auth_config(cfg):
            return cfg
    except Exception:
        pass
    return None

app = FastAPI()

chara_map = {}
support_map = {}
active_client = None
active_account = None
active_dashboard_data = None
active_start_state = {}
active_support_card_deck_array = []
active_parent_cards = {}
active_parent_rank_points = {}
active_parent_full = {}  # trained_chara_id -> full trained-chara dict (for affinity calc)
pending_game_auth_config = {}
raw_load_index_response = None
active_selection = {
    "deck": None,
    "friend": None,
    "trainee": None,
    "veterans": []
}
turn_delay_min_sec = 2.5
turn_delay_max_sec = 5.0
turn_delay_restore_min_sec = 2.5
turn_delay_restore_max_sec = 5.0
turn_delay_disabled = False
preset_store = PresetStore(DIR)
career_runner = CareerRunner(DIR)
dailies_runner = DailiesRunner(DIR)
global_lock = threading.Lock()

base_dir = Path(__file__).parent.absolute()

class _CampaignPresetStore:
    def load(self, name):
        preset = preset_store.read_one(name)
        if not preset:
            raise ValueError(f"Campaign preset not found: {name}")
        return preset

    def save(self, preset):
        return preset_store.write(preset)

def _runtime_account_name():
    runtime_override = os.environ.get("UMA_RUNTIME_DIR")
    if not runtime_override:
        return ""
    runtime_name = Path(runtime_override).expanduser().resolve().name
    return runtime_name if runtime_name != "uma_runtime" else ""


def _current_campaign_account():
    dashboard = active_dashboard_data or {}
    account = active_account or dashboard.get("account") or {}
    if isinstance(account, str):
        return account
    if not isinstance(account, dict):
        account = {}
    return str(
        dashboard.get("account_name")
        or dashboard.get("accountName")
        or account.get("name")
        or account.get("account")
        or _runtime_account_name()
        or "local"
    )

def _assert_campaign_account(account):
    requested = str(account or "").strip()
    current = _current_campaign_account().strip()
    if requested and current and requested != current:
        raise ValueError(f"Campaign account {requested} does not match active account {current}")

def _campaign_runtime_snapshot(account):
    _assert_campaign_account(account)
    dashboard = active_dashboard_data or {}
    display_rows = [
        *(dashboard.get("displayVeterans") or []),
        *(dashboard.get("parents") or []),
        *(dashboard.get("friendVeterans") or []),
    ]
    display_by_id = {
        int(row.get("trained_chara_id") or row.get("instance_id") or 0): dict(row)
        for row in display_rows
        if isinstance(row, dict) and int(row.get("trained_chara_id") or row.get("instance_id") or 0)
    }
    owned_chara_ids = {
        _base_chara_id(row.get("id") or row.get("card_id"))
        for row in (dashboard.get("umas") or [])
        if isinstance(row, dict)
    }
    rental_candidates = [
        dict(row)
        for row in (
            dashboard.get("rentalCandidates")
            or dashboard.get("rental_candidates")
            or dashboard.get("friendVeterans")
            or []
        )
        if isinstance(row, dict)
    ]
    current_account = active_account or dashboard.get("account") or {}
    current_runner = career_runner.snapshot()
    try:
        base_aptitudes = aptitude._load_chara_aptitude(base_dir / "data")
    except Exception:
        base_aptitudes = {}
    try:
        race_rows = _campaign_race_rows()
    except Exception:
        race_rows = []
    g1_saddle_program_map = {}
    try:
        mdb_path = master_data.configured_master_mdb_path(base_dir)
        if mdb_path:
            g1_saddle_program_map = affinity_calc.load_g1_saddle_program_map(str(mdb_path))
    except Exception:
        g1_saddle_program_map = {}
    return {
        "account": account,
        "current_account": current_account,
        "current_career": current_account.get("career") if isinstance(current_account, dict) else None,
        "owned_candidates": [dict(row) for row in active_parent_full.values()],
        "rental_candidates": rental_candidates,
        "display_by_id": display_by_id,
        "umas": [dict(row) for row in (dashboard.get("umas") or []) if isinstance(row, dict)],
        "decks": [
            deepcopy(dict(row))
            for row in (dashboard.get("decks") or [])
            if isinstance(row, dict)
        ],
        "base_aptitudes": base_aptitudes,
        "race_rows": race_rows,
        "g1_saddle_program_map": g1_saddle_program_map,
        "owned_chara_ids": {value for value in owned_chara_ids if value > 0},
        "runtime": {
            "api_reachable": active_client is not None,
            "logged_in": active_client is not None,
        },
        "bot_state": {
            "session": {"logged_in": active_client is not None},
            "career_runner": {
                "running": bool(current_runner.get("running")),
                "finished": bool(current_runner.get("finished")),
            },
            "dailies": {"running": bool(dailies_runner.running)},
        },
    }

def _campaign_parent_id(row):
    if not isinstance(row, dict):
        return 0
    return _positive_runtime_id(
        row.get("trained_chara_id") or row.get("instance_id") or row.get("id")
    )


def _campaign_spark_totals(display_parent):
    totals = {}
    tree = display_parent.get("tree") if isinstance(display_parent, dict) else {}
    nodes = tree.values() if isinstance(tree, dict) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for factor in node.get("factors") or []:
            if not isinstance(factor, dict):
                continue
            category = str(factor.get("category") or "").strip().lower()
            normalized_category = {
                "stat": "blue",
                "blue": "blue",
                "aptitude": "pink",
                "pink": "pink",
            }.get(category)
            name = str(factor.get("name") or "").strip().lower()
            if not normalized_category or not name:
                continue
            try:
                stars = max(0, int(factor.get("stars") or 0))
            except (TypeError, ValueError):
                stars = 0
            key = (normalized_category, name)
            totals[key] = totals.get(key, 0) + stars
    return totals


def _campaign_completed_result(campaign, snapshot):
    context = campaign.get("context") or {}
    prepared = context.get("prepared_run") or {}
    expected_card_id = _positive_runtime_id(prepared.get("card_id"))
    expected_trainee = _positive_runtime_id(prepared.get("trainee_chara_id"))
    baseline_ids = {
        _positive_runtime_id(value)
        for value in (context.get("baseline_parent_ids") or [])
        if _positive_runtime_id(value)
    }
    owned = [dict(row) for row in (snapshot.get("owned_candidates") or []) if isinstance(row, dict)]
    owned_by_id = {
        _campaign_parent_id(row): row
        for row in owned
        if _campaign_parent_id(row)
    }
    parent_ids = sorted(owned_by_id)

    candidates = []
    for trained_id, row in owned_by_id.items():
        if baseline_ids and trained_id in baseline_ids:
            continue
        candidate_card_id = _positive_runtime_id(
            row.get("card_id") or row.get("race_cloth_id")
        )
        if expected_card_id and candidate_card_id != expected_card_id:
            continue
        if (
            not expected_card_id
            and expected_trainee
            and _base_chara_id(candidate_card_id) != expected_trainee
        ):
            continue
        candidates.append(row)
    if not candidates:
        raise ValueError("No new trained veteran was found after the completed Career")
    candidates.sort(
        key=lambda row: (
            str(row.get("create_time") or row.get("register_time") or row.get("created_at") or ""),
            int(row.get("rank_score") or 0),
            _campaign_parent_id(row),
        ),
        reverse=True,
    )
    raw_candidate = candidates[0]
    trained_id = _campaign_parent_id(raw_candidate)
    display = (snapshot.get("display_by_id") or {}).get(trained_id) or {}
    spec_version = int(((campaign.get("spec") or {}).get("spec_version") or 0))
    factor_tree = deepcopy(display.get("tree") or {})
    self_totals = self_spark_totals(factor_tree)
    direct_totals = direct_lineage_spark_totals(factor_tree)
    candidate = {
        **raw_candidate,
        "candidate_id": f"veteran-{trained_id}",
        "trained_chara_id": trained_id,
        "name": str(display.get("name") or raw_candidate.get("name") or f"Veteran #{trained_id}"),
        "spark_totals": direct_totals if spec_version >= 3 else _campaign_spark_totals(display),
        "self_spark_totals": self_totals,
        "direct_lineage_spark_totals": direct_totals,
        "factor_tree": factor_tree,
    }

    if spec_version >= 3 or isinstance(context.get("stage_state"), dict):
        candidate["displayed_affinity"] = affinity_calc.calculate_veteran_affinity(
            _campaign_master_mdb_path(),
            raw_candidate,
        )
        return candidate, [], parent_ids

    final_parent_id = _positive_runtime_id(
        ((campaign.get("spec") or {}).get("final_parent") or {}).get("trained_chara_id")
    )
    final_parent = owned_by_id.get(final_parent_id)
    if not final_parent:
        raise ValueError(f"Final parent veteran {final_parent_id} is unavailable")
    pairings = [{**final_parent, "rental": False}]
    return candidate, pairings, parent_ids


def _refresh_campaign_runtime_snapshot(account):
    if not active_client:
        raise ValueError("Campaign result collection requires login")
    response = active_client.call("load/index", {"adid": ""})
    data = response.get("data", {}) if isinstance(response, dict) else {}
    active_client.refresh_cached_account_state(data)
    update_start_state(data)
    _build_dashboard_from_login_response(response)
    return _campaign_runtime_snapshot(account)


def _campaign_advance(campaign_id):
    campaign = campaign_store.get(campaign_id)
    snapshot = _campaign_runtime_snapshot(campaign["account"])
    runtime = snapshot.get("runtime", snapshot)
    bot_state = snapshot.get("bot_state", snapshot)
    current_career = snapshot.get("current_career")
    runner_state = (
        bot_state.get("career_runner")
        if isinstance(bot_state.get("career_runner"), dict)
        else {}
    )
    execution_state = campaign.get("state") in {"RUNNING_CAREER", "EVALUATING_RESULT"}
    if (
        execution_state
        and isinstance(current_career, dict)
        and current_career.get("active") is True
        and runner_state.get("finished")
    ):
        # A finished local thread can mean either a genuinely completed Career
        # or a crashed runner while the server Career is still active. Refresh
        # the account before choosing between result collection and resume.
        confirmed = _refresh_campaign_runtime_snapshot(campaign["account"])
        confirmed_career = confirmed.get("current_career")
        if isinstance(confirmed_career, dict) and confirmed_career.get("active") is True:
            snapshot = confirmed
            current_career = confirmed_career
            runtime = confirmed.get("runtime", runtime)
            bot_state = confirmed.get("bot_state", bot_state)
            runner_state = (
                bot_state.get("career_runner")
                if isinstance(bot_state.get("career_runner"), dict)
                else {}
            )
        else:
            current_career = confirmed_career
    if (
        campaign.get("state") == "SELECTING_LINEAGE"
        and not (isinstance(current_career, dict) and current_career.get("active") is True)
    ):
        context = campaign.get("context") or {}
        if campaign.get("next_action") != "start_career" or not context.get("prepared_run"):
            prepared = campaign_service.prepare_next_run(campaign_id)
            campaign = prepared.get("campaign", prepared)
            context = campaign.get("context") or {}
        if (
            campaign.get("state") == "SELECTING_LINEAGE"
            and campaign.get("next_action") == "start_career"
            and context.get("review_required") is False
        ):
            campaign_service.approve_run(campaign_id)
            campaign = campaign_store.get(campaign_id)
        return {"campaign": campaign}

    if (
        execution_state
        and isinstance(current_career, dict)
        and current_career.get("active") is True
    ):
        prepared = dict((campaign.get("context") or {}).get("prepared_run") or {})
        trusted_current = {
            **current_career,
            "account": str(campaign.get("account") or ""),
            "campaign_id": str(campaign_id),
        }
        if not CampaignService._career_matches_prepared_run(trusted_current, prepared):
            reconciled = campaign_service.reconcile_runtime(campaign_id, trusted_current)
            return {"campaign": CampaignService._campaign_from_reconciliation(reconciled)}
        if not runner_state.get("running"):
            campaign_service.start_career(deepcopy(prepared))
        if campaign.get("state") != "RUNNING_CAREER" or campaign.get("next_action") != "monitor_career":
            campaign = campaign_store.transition(
                campaign_id,
                "RUNNING_CAREER",
                next_action="monitor_career",
                context_updates={"runtime_reconciliation": {"status": "MATCHED"}},
            )
        return {"campaign": campaign}

    advanced = campaign_runner.reconcile(
        campaign_id,
        runtime=runtime,
        bot_state=bot_state,
    )
    if advanced.get("state") != "EVALUATING_RESULT":
        return {"campaign": advanced}

    refreshed = _refresh_campaign_runtime_snapshot(campaign["account"])
    current = campaign_store.get(campaign_id)
    candidate, pairings, parent_ids = _campaign_completed_result(current, refreshed)
    result = campaign_service.record_completed_veteran(
        campaign_id,
        candidate,
        pairings,
    )
    updated = campaign_store.update_context(
        campaign_id,
        {
            "baseline_parent_ids": parent_ids,
            "run_start": None,
            "runtime_reconciliation": {"status": "MATCHED"},
            "last_result": {
                "trained_chara_id": candidate["trained_chara_id"],
                "candidate_id": candidate["candidate_id"],
                "decision": result.get("decision", ""),
            },
        },
    )
    return {
        **result,
        "campaign": updated,
    }


def _campaign_master_mdb_path():
    path = master_data.configured_master_mdb_path(base_dir)
    if not path or not Path(path).exists():
        raise ValueError("Campaign recommendations require configured master.mdb data")
    return str(path)

def _campaign_race_rows():
    path = base_dir / "public" / "assets" / "data" / "uma_race_data.json"
    if not path.exists():
        path = base_dir / "public" / "uma_race_data.json"
    if not path.exists():
        raise ValueError("Campaign recommendations require generated race data")
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("races") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("Campaign race data has no races array")
    return rows

def _campaign_affinity(final_uma, first, second):
    card_id = int((final_uma or {}).get("card_id") or 0) if isinstance(final_uma, dict) else int(final_uma or 0)
    if card_id <= 0:
        raise ValueError("Campaign final Uma card_id is required for affinity")
    return affinity_calc.calculate_affinity(_campaign_master_mdb_path(), card_id, first, second)


def _campaign_direct_compatibility(final_card_id, parent_chara_id):
    final_chara_id = affinity_calc.card_to_chara_id(int(final_card_id or 0))
    return affinity_calc.direct_relation_score(
        _campaign_master_mdb_path(),
        final_chara_id,
        int(parent_chara_id or 0),
    )


def _campaign_projected_affinity(trainee_card_id, first, second, planned_g1_saddle_ids):
    return affinity_calc.project_displayed_veteran_affinity(
        _campaign_master_mdb_path(),
        trainee_card_id=int(trainee_card_id or 0),
        parent1=first,
        parent2=second,
        planned_g1_saddle_ids=set(planned_g1_saddle_ids or set()),
    )


class _ConfiguredCampaignPlanner(CampaignPlanner):
    def __init__(self, *, mdb_path, **kwargs):
        super().__init__(**kwargs)
        self.mdb_path = mdb_path

    def recommend_bootstraps(
        self,
        *,
        pinned_chara_ids=None,
        limit=3,
        mdb_path="",
    ):
        return super().recommend_bootstraps(
            pinned_chara_ids=pinned_chara_ids,
            limit=limit,
            mdb_path=mdb_path or self.mdb_path,
        )

    def recommend_loops(
        self,
        *,
        pinned_chara_ids=None,
        final_parent_chara_id=0,
        limit=3,
        mdb_path="",
    ):
        return super().recommend_loops(
            pinned_chara_ids=pinned_chara_ids,
            final_parent_chara_id=final_parent_chara_id,
            limit=limit,
            mdb_path=mdb_path or self.mdb_path,
        )

def _campaign_planner_factory(request):
    payload = dict(request)
    snapshot = _campaign_runtime_snapshot(payload.get("account") or _current_campaign_account())
    mdb_path = _campaign_master_mdb_path()
    veteran_by_id = {}
    for row in [*snapshot["owned_candidates"], *snapshot["rental_candidates"]]:
        trained_id = int(row.get("trained_chara_id") or row.get("instance_id") or 0)
        if trained_id:
            veteran_by_id.setdefault(trained_id, dict(row))
    final_uma = payload.get("final_uma") or {}
    return _ConfiguredCampaignPlanner(
        mdb_path=mdb_path,
        owned_chara_ids=set(snapshot["owned_chara_ids"]),
        veteran_records=list(veteran_by_id.values()),
        display_by_id=dict(snapshot["display_by_id"]),
        g1_saddle_ids=set(affinity_calc._load_g1_saddles(mdb_path)),
        race_rows=_campaign_race_rows(),
        affinity_for_pair=lambda trainee, first, second: affinity_calc.calculate_affinity(
            mdb_path, trainee, first, second
        ),
        direct_compatibility_for_parent=lambda final_card_id, parent_chara_id: affinity_calc.direct_relation_score(
            mdb_path,
            affinity_calc.card_to_chara_id(int(final_card_id or 0)),
            int(parent_chara_id or 0),
        ),
        factor_map=factor_map,
        spark_targets=payload.get("spark_targets") or [],
        final_uma_card_id=int(payload.get("final_uma_card_id") or final_uma.get("card_id") or 0),
    )

def _positive_runtime_id(value):
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _campaign_runtime_friends():
    global active_dashboard_data
    dashboard = active_dashboard_data or {}
    friends = [dict(row) for row in (dashboard.get("friends") or []) if isinstance(row, dict)]
    if friends:
        return friends
    refresh = getattr(active_client, "pre_single_mode", None)
    if not callable(refresh):
        return []
    result = refresh([])
    data = result.get("data", {}) if isinstance(result, dict) else {}
    update_start_state(data)
    friends, exclude_viewer_ids, _source = normalize_friend_cards(data)
    if active_dashboard_data is not None:
        active_dashboard_data["friends"] = friends
        active_dashboard_data["friendExcludeIds"] = exclude_viewer_ids
        active_dashboard_data["friendsLoaded"] = True
    return friends


def _resolve_campaign_friend_support(friend_support, preset, *, support_ids, trainee_chara_id):
    requested = friend_support if isinstance(friend_support, dict) else {}
    support_card_id = _positive_runtime_id(
        requested.get("support_card_id")
        or requested.get("friend_card_id")
        or preset.get("friend_card_id")
    )
    viewer_id = _positive_runtime_id(
        requested.get("viewer_id")
        or requested.get("friend_viewer_id")
        or preset.get("friend_viewer_id")
    )
    if support_card_id <= 0:
        return 0, 0
    if support_card_id in set(support_ids):
        raise ValueError(f"Friend support {support_card_id} is already present in campaign deck")
    if viewer_id > 0:
        return viewer_id, support_card_id

    trainee_name = next(
        (
            str(row.get("name") or "")
            for row in ((active_dashboard_data or {}).get("umas") or [])
            if _base_chara_id(row.get("id") or row.get("card_id")) == trainee_chara_id
        ),
        "",
    )
    normalized_trainee = normalize_card_name(trainee_name)
    candidates = []
    for row in _campaign_runtime_friends():
        if _positive_runtime_id(row.get("support_card_id")) != support_card_id:
            continue
        candidate_viewer_id = _positive_runtime_id(row.get("viewer_id"))
        if candidate_viewer_id <= 0:
            continue
        support_name = str(row.get("support_name") or "")
        if normalized_trainee and normalize_card_name(support_name) == normalized_trainee:
            continue
        candidates.append((
            -int(_positive_runtime_id(row.get("friend_state")) >= 2),
            -int(bool(_positive_runtime_id(row.get("favorite_flag")))),
            -_positive_runtime_id(row.get("exp")),
            candidate_viewer_id,
        ))
    if not candidates:
        raise ValueError(
            f"Friend support {support_card_id} is no longer available; reload friend supports and rebuild the prepared run"
        )
    candidates.sort()
    return candidates[0][3], support_card_id


def _campaign_start_career(request):
    _assert_campaign_account(request.get("account"))
    if not active_client:
        raise ValueError("Campaign career start requires login")
    preset = dict(request.get("preset") or {})
    slots = list(request.get("legacy_slots") or request.get("parents") or [])
    parent_ids = [int(row.get("trained_chara_id") or 0) for row in slots if isinstance(row, dict)]
    if len(parent_ids) < 2 or not all(parent_ids[:2]):
        raise ValueError("Campaign prepared run requires two resolved parents")
    deck_id = int(request.get("deck_id") or 0)
    dashboard_deck = next((row for row in ((active_dashboard_data or {}).get("decks") or []) if int(row.get("id") or row.get("deck_id") or 0) == deck_id), None)
    raw_deck = next((row for row in (active_support_card_deck_array or []) if int(row.get("deck_id") or row.get("id") or 0) == deck_id), None)
    if dashboard_deck:
        support_ids = [int(row.get("id") or row.get("support_card_id") or 0) for row in (dashboard_deck.get("cards") or [])]
    else:
        support_ids = [int(value or 0) for value in ((raw_deck or {}).get("support_card_id_array") or [])]
    trainee_chara_id = int(request.get("trainee_chara_id") or 0)
    friend_support = request.get("friend_support") or (active_selection or {}).get("friend") or {}
    friend_viewer_id, friend_card_id = _resolve_campaign_friend_support(
        friend_support,
        preset,
        support_ids=support_ids,
        trainee_chara_id=trainee_chara_id,
    )
    if len(support_ids) != 5 or not all(support_ids) or not friend_viewer_id or not friend_card_id:
        raise ValueError("Campaign preset requires five supports and a friend support")
    prepared_card_id = _positive_runtime_id(
        request.get("card_id") or request.get("trainee_card_id")
    )
    if prepared_card_id > 0:
        card_id = prepared_card_id
    else:
        card_id = next(
            (
                int(row.get("id") or row.get("card_id") or 0)
                for row in ((active_dashboard_data or {}).get("umas") or [])
                if _base_chara_id(row.get("id") or row.get("card_id")) == trainee_chara_id
            ),
            trainee_chara_id,
        )

    runtime_trainee = next(
        (
            dict(row)
            for row in ((active_dashboard_data or {}).get("umas") or [])
            if _positive_runtime_id(row.get("id") or row.get("card_id")) == card_id
        ),
        {"id": card_id, "name": chara_map.get(str(card_id), "")},
    )
    resolved_deck = dashboard_deck or {
        "id": deck_id,
        "name": f"Deck {deck_id}",
        "cards": [
            {
                "id": support_id,
                "name": str((support_map.get(str(support_id)) or {}).get("name") or ""),
            }
            for support_id in support_ids
        ],
    }
    deck_conflicts = find_trainee_deck_conflicts(resolved_deck, runtime_trainee)
    if deck_conflicts:
        support_names = ", ".join(
            str(row.get("support_name") or row.get("support_card_id") or "unknown")
            for row in deck_conflicts
        )
        trainee_name = str(runtime_trainee.get("name") or card_id)
        raise ValueError(
            f"{trainee_name} cannot start with Deck {deck_id}: "
            f"same-character support found ({support_names})"
        )

    race_overrides = request.get("race_overrides") or []
    preset_overrides = dict(preset.get("preset_overrides") or {})
    if isinstance(race_overrides, dict):
        for key in ("mandatory_race_list", "extra_race_list"):
            if key in race_overrides:
                preset_overrides[key] = list(race_overrides[key] or [])
    elif isinstance(race_overrides, list):
        preset_overrides["extra_race_list"] = list(race_overrides)
    else:
        raise ValueError("Campaign race_overrides must be a list or mapping")
    if "parent_run" in preset:
        preset_overrides["parent_run"] = bool(preset["parent_run"])
    career_request = RunCareerRequest(
        card_id=card_id,
        support_card_ids=support_ids,
        friend_viewer_id=friend_viewer_id,
        friend_card_id=friend_card_id,
        parent_id_1=parent_ids[0],
        parent_id_2=parent_ids[1],
        scenario_id=int(preset.get("scenario_id") or preset.get("scenario") or 4),
        deck_id=deck_id,
        use_tp=int(preset.get("use_tp") or 30),
        preset_name=str(preset.get("name") or preset.get("preset_name") or ""),
        preset_overrides=preset_overrides,
    )
    current_career = (
        active_account.get("career")
        if isinstance(active_account, dict) and isinstance(active_account.get("career"), dict)
        else {}
    )
    if current_career.get("active") is True:
        trusted_current = {
            **current_career,
            "account": str(request.get("account") or ""),
            "campaign_id": str(request.get("campaign_id") or ""),
        }
        if not CampaignService._career_matches_prepared_run(trusted_current, request):
            raise ValueError("Current active career does not match the campaign prepared run")
        career_result = active_client.load_career(scenario_id=career_request.scenario_id)
        if not ((career_result.get("data") or {}).get("chara_info")):
            raise ValueError("Current active career could not be loaded for resume")
    else:
        started = start_career_from_request(career_request)
        if not started.get("success"):
            raise ValueError(started.get("detail") or "Campaign career start failed")
        career_result = started.get("result") or {}
    runtime_preset = apply_runtime_preset_overrides(preset, preset_overrides)
    _apply_preset_turn_delay(runtime_preset)
    account, chara_info = apply_career_result(career_result)
    career_status = account.get("career") if isinstance(account, dict) else None
    if isinstance(career_status, dict):
        career_status.update({
            "trainee_chara_id": trainee_chara_id,
            "deck_id": deck_id,
            "parent_id_1": parent_ids[0],
            "parent_id_2": parent_ids[1],
        })
    apply_deck_type_counts(runtime_preset, req=career_request, chara_info=chara_info)
    career_runner.start(
        active_client,
        runtime_preset,
        career_result,
        career_request.max_steps,
        burn_clocks=bool(runtime_preset.get("burn_clocks", False)),
        dev_mode=False,
    )
    return {
        "success": True,
        "result": career_result,
        "account": account,
        "chara_info": chara_info,
        "runner": _career_runner_snapshot(),
    }

campaign_store = CampaignStore(
    os.environ.get("SWEEPY_CAMPAIGNS_DB")
    or base_dir / "uma_runtime" / "campaigns.sqlite3"
)
campaign_runner = CampaignRunner(campaign_store)
campaign_service = CampaignService(
    store=campaign_store,
    runner=campaign_runner,
    preset_store=_CampaignPresetStore(),
    runtime_snapshot=_campaign_runtime_snapshot,
    affinity_for_setup=_campaign_affinity,
    projected_affinity_for_pair=_campaign_projected_affinity,
    direct_compatibility_for_parent=_campaign_direct_compatibility,
    start_career=_campaign_start_career,
    planner_factory=_campaign_planner_factory,
)

master_data_startup_status = master_data.status(base_dir)
if master_data_startup_status.get("exists"):
    master_data_startup_result = master_data.generate(base_dir)
    if master_data_startup_result.get("success"):
        print(f"master.mdb data generated: {master_data_startup_status.get('master_mdb_path')}")
    else:
        print(f"master.mdb data generation failed: {master_data_startup_result.get('detail')}")
elif master_data_startup_status.get("requires_user_action"):
    print(f"master.mdb requires user action: {master_data_startup_status.get('master_mdb_path')}")
chara_path = base_dir / 'data' / 'chara_list.json'
support_path = base_dir / 'data' / 'support_list.json'
images_dir = base_dir / 'data' / 'images'

if chara_path.exists():
    with open(chara_path, 'r', encoding='utf-8') as f:
        chara_map = json.load(f)
if support_path.exists():
    with open(support_path, 'r', encoding='utf-8') as f:
        support_map = json.load(f)

def display_support_type(value):
    return {
        "Friends": "Pal",
        "Wisdom": "Wit"
    }.get(value, value)


def normalize_turn_delay(min_value, max_value, disabled=False):
    left = max(0.0, float(min_value or 0.0))
    right = max(0.0, float(max_value or 0.0))
    if left > right:
        right = left
    if disabled:
        left = 0.0
        right = 0.0
    return left, right, bool(disabled)

def set_turn_delay(min_value, max_value, disabled=False):
    import career_bot.delay as delay_module
    next_min, next_max, next_disabled = normalize_turn_delay(min_value, max_value, disabled)
    if not next_disabled:
        delay_module.TURN_DELAY_RESTORE_MIN = next_min
        delay_module.TURN_DELAY_RESTORE_MAX = next_max
    delay_module.TURN_DELAY_MIN = next_min
    delay_module.TURN_DELAY_MAX = next_max
    delay_module.GLOBAL_DELAYS_DISABLED = next_disabled
    return get_turn_delay()

def get_turn_delay():
    import career_bot.delay as delay_module
    return {
        "success": True,
        "min": getattr(delay_module, "TURN_DELAY_MIN", 2.5),
        "max": getattr(delay_module, "TURN_DELAY_MAX", 5.0),
        "restore_min": getattr(delay_module, "TURN_DELAY_RESTORE_MIN", 2.5),
        "restore_max": getattr(delay_module, "TURN_DELAY_RESTORE_MAX", 5.0),
        "disabled": getattr(delay_module, "GLOBAL_DELAYS_DISABLED", False)
    }

def _apply_preset_turn_delay(preset):
    """Apply turn-delay values from a preset dict to the global delay module."""
    min_sec = preset.get("turn_delay_min_sec")
    max_sec = preset.get("turn_delay_max_sec")
    disabled = preset.get("turn_delay_disabled", False)
    if min_sec is not None and max_sec is not None:
        set_turn_delay(float(min_sec), float(max_sec), bool(disabled))

def update_start_state(data):
    global active_start_state, active_support_card_deck_array
    if not data:
        return
    if data.get('tp_info'):
        tp_info = dict(data.get('tp_info'))
        active_start_state['tp_info'] = tp_info
    item_list = data.get('item_list') or data.get('user_item_array') or data.get('user_item')
    if isinstance(item_list, list) and item_list:
        active_start_state['current_money'] = get_item_count(item_list, 59)
        active_start_state['succession_rank_point'] = get_item_count(item_list, 75)
    elif active_client:
        # Most endpoints don't return item_list — use item_map updated by call() internally
        active_start_state['current_money'] = active_client.item_map.get(59, 0)
        active_start_state['succession_rank_point'] = active_client.item_map.get(75, 0)
    if isinstance(data.get('support_card_deck_array'), list):
        active_support_card_deck_array = data.get('support_card_deck_array')


def normalize_friend_cards(data):
    source = 'refresh'
    friend_data = data.get('friend_support_card_data')
    if friend_data:
        source = 'initial'
        summaries = friend_data.get('summary_user_info_array', [])
        support_cards = friend_data.get('support_card_data_array', [])
    else:
        summaries = data.get('summary_user_info_array', [])
        support_cards = data.get('support_card_data_array', [])

    support_by_key = {}
    for sc in support_cards or []:
        key = (sc.get('viewer_id'), sc.get('support_card_id'))
        support_by_key[key] = sc

    friends = []
    exclude_viewer_ids = []
    seen = set()
    for info in summaries or []:
        viewer_id = info.get('viewer_id')
        support_card_id = info.get('support_card_id')
        if not viewer_id or not support_card_id:
            continue
        key = (viewer_id, support_card_id)
        if key in seen:
            continue
        seen.add(key)
        exclude_viewer_ids.append(viewer_id)
        card_data = support_by_key.get(key) or info.get('user_support_card') or {}
        support_info = support_map.get(str(support_card_id), {})
        friends.append({
            'viewer_id': viewer_id,
            'name': info.get('name', ''),
            'support_card_id': support_card_id,
            'support_name': support_info.get('name', f"Unknown ({support_card_id})"),
            'rarity': support_info.get('rarity', '?'),
            'type': display_support_type(support_info.get('type', 'Unknown')),
            'exp': card_data.get('exp', info.get('user_support_card', {}).get('exp')),
            'limit_break_count': card_data.get('limit_break_count', info.get('user_support_card', {}).get('limit_break_count')),
            'favorite_flag': card_data.get('favorite_flag', 0),
            'friend_state': info.get('friend_state', 0)
        })
    return friends, exclude_viewer_ids, source


def _refresh_dashboard_friend_supports():
    """Fetch one current friend-support snapshot without blocking the UI on failure."""
    global active_dashboard_data
    dashboard = active_dashboard_data or {}
    cached_friends = list(dashboard.get("friends") or [])
    if active_client is None:
        return cached_friends
    career = (active_account or {}).get("career") or {}
    if career.get("active"):
        return cached_friends
    try:
        result = active_client.pre_single_mode()
        data = result.get("data", {}) if isinstance(result, dict) else {}
        update_start_state(data)
        friends, exclude_viewer_ids, _source = normalize_friend_cards(data)
        veterans, veterans_source = normalize_friend_veterans(data)
        if active_dashboard_data is not None:
            active_dashboard_data["friends"] = friends
            active_dashboard_data["friendExcludeIds"] = exclude_viewer_ids
            active_dashboard_data["friendsLoaded"] = True
            active_dashboard_data["friendVeterans"] = veterans
            active_dashboard_data["friendVeteransSource"] = veterans_source
            active_dashboard_data["lastPreSingleModeRaw"] = data
        return friends
    except Exception:
        return cached_friends


def normalize_card_name(name):
    return re.sub(r'[^a-z0-9]+', '', re.sub(r'\([^)]*\)', '', str(name or '').lower()))


def _load_data_file(filename):
    path = base_dir / 'data' / filename
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _support_cards_from_ids(card_ids):
    result = []
    for cid in card_ids:
        info = support_map.get(str(cid), {})
        result.append({
            'card_id': cid,
            'name': info.get('name', f'Unknown ({cid})'),
            'type': info.get('type', 'Unknown'),
            'rarity': info.get('rarity', '?'),
        })
    return result


def _deck_meta_from_ids(card_ids):
    counts = advisor.support_type_counts(card_ids, support_map)
    return {
        'deck_support_cards': _support_cards_from_ids(card_ids),
        'deck_type_counts': counts,
        'deck_archetype': advisor.deck_archetype(counts),
    }


def _dashboard_deck_from_raw(deck, owned_supports=None):
    lb_by_id = {
        str(item.get('id')): int(item.get('limit_break_count') or 0)
        for item in (owned_supports or [])
        if item.get('id') is not None
    }
    cards = []
    for card_id in deck.get('support_card_id_array') or []:
        sid = str(int(card_id or 0))
        if sid == '0':
            continue
        info = support_map.get(sid) or {}
        cards.append({
            'id': sid,
            'limit_break_count': lb_by_id.get(sid, 0),
            'name': info.get('name', f'Unknown ({sid})'),
            'rarity': info.get('rarity', '?'),
            'type': display_support_type(info.get('type', 'Unknown')),
        })
    deck_id = int(deck.get('deck_id') or 0)
    return {
        'id': deck_id,
        'name': str(deck.get('name') or f'Deck {deck_id}'),
        'cards': cards,
    }


def _replace_support_deck_party(current_decks, deck_id, name, support_card_ids):
    deck_id = int(deck_id or 0)
    if deck_id < 1 or deck_id > 10:
        raise ValueError('deck_id must be between 1 and 10')
    card_ids = [int(card_id or 0) for card_id in (support_card_ids or []) if int(card_id or 0)]
    if len(card_ids) > 5:
        raise ValueError('A support deck can contain at most 5 owned cards')
    if len(set(card_ids)) != len(card_ids):
        raise ValueError('A support deck cannot contain duplicate cards')

    by_id = {
        int(deck.get('deck_id') or 0): dict(deck)
        for deck in (current_decks or [])
        if 1 <= int(deck.get('deck_id') or 0) <= 10
    }
    normalized = []
    for current_id in range(1, 11):
        deck = by_id.get(current_id) or {
            'deck_id': current_id,
            'name': f'Deck {current_id}',
            'support_card_id_array': [0, 0, 0, 0, 0],
        }
        if current_id == deck_id:
            deck = {
                'deck_id': current_id,
                'name': str(name or '').strip() or f'Deck {current_id}',
                'support_card_id_array': card_ids + [0] * (5 - len(card_ids)),
            }
        else:
            existing_ids = [int(value or 0) for value in (deck.get('support_card_id_array') or [])][:5]
            deck = {
                'deck_id': current_id,
                'name': str(deck.get('name') or f'Deck {current_id}'),
                'support_card_id_array': existing_ids + [0] * (5 - len(existing_ids)),
            }
        normalized.append(deck)
    return normalized


FRIEND_VETERAN_KEYS = ('succession_trained_chara_array',)
FRIEND_VETERAN_CONTAINER_KEYS = (
    'succession_trained_chara_data',
    'event_succession_trained_chara_data',
)


def _extract_veteran_rows(data):
    candidates = []

    def absorb(value):
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    candidates.append(item)

    for container_key in FRIEND_VETERAN_CONTAINER_KEYS:
        container = data.get(container_key) or {}
        if isinstance(container, dict):
            for key in FRIEND_VETERAN_KEYS:
                absorb(container.get(key))
    for key in FRIEND_VETERAN_KEYS:
        absorb(data.get(key))
    return candidates


def normalize_friend_veterans(data):
    global active_parent_rank_points
    rows = _extract_veteran_rows(data)
    if not rows:
        return [], 'no_data'

    summaries_by_viewer = {}
    for info in data.get('summary_user_info_array', []) or []:
        vid = info.get('viewer_id')
        if vid is not None:
            summaries_by_viewer.setdefault(vid, info)
    friend_data = data.get('friend_support_card_data') or {}
    for info in friend_data.get('summary_user_info_array', []) or []:
        vid = info.get('viewer_id')
        if vid is not None:
            summaries_by_viewer.setdefault(vid, info)
    for ckey in FRIEND_VETERAN_CONTAINER_KEYS:
        cinfo = data.get(ckey) or {}
        if isinstance(cinfo, dict):
            for info in cinfo.get('summary_user_info_array', []) or []:
                vid = info.get('viewer_id')
                if vid is not None:
                    summaries_by_viewer.setdefault(vid, info)

    out = []
    seen = set()
    for row in rows:
        viewer_id = row.get('viewer_id') or row.get('owner_viewer_id') or 0
        trained_chara_id = row.get('trained_chara_id') or row.get('id') or 0
        card_id = row.get('card_id') or row.get('chara_id') or 0
        if not viewer_id or not trained_chara_id:
            continue
        key = (int(viewer_id), int(trained_chara_id))
        if key in seen:
            continue
        seen.add(key)

        active_parent_rank_points[int(trained_chara_id)] = {
            'rank': int(row.get('rank') or 0),
            'rank_score': int(row.get('rank_score') or 0),
        }

        summary = summaries_by_viewer.get(viewer_id) or {}
        chara_name = chara_map.get(str(card_id), f'Unknown ({card_id})')

        factors = []
        try:
            factors = get_factors(get_chara_factor_ids(row), card_id)
        except Exception:
            factors = []

        tree = {
            'self': {
                'card_id': int(card_id),
                'name': chara_name,
                'factors': factors,
                'wins': get_win_summary(row.get('win_saddle_id_array') or []),
            },
            'p1': {'card_id': 0, 'name': '', 'factors': [], 'wins': get_win_summary([])},
            'p2': {'card_id': 0, 'name': '', 'factors': [], 'wins': get_win_summary([])},
            'gp1': {'card_id': 0, 'name': '', 'factors': [], 'wins': get_win_summary([])},
            'gp2': {'card_id': 0, 'name': '', 'factors': [], 'wins': get_win_summary([])},
            'gp3': {'card_id': 0, 'name': '', 'factors': [], 'wins': get_win_summary([])},
            'gp4': {'card_id': 0, 'name': '', 'factors': [], 'wins': get_win_summary([])},
        }
        parent_card_ids = []
        lineage_keys = {10: 'p1', 20: 'p2', 11: 'gp1', 12: 'gp2', 21: 'gp3', 22: 'gp4'}
        for sc in row.get('succession_chara_array') or []:
            pos = sc.get('position_id')
            tree_key = lineage_keys.get(pos)
            if not tree_key:
                continue
            lineage_card_id = int(sc.get('card_id') or 0)
            factor_ids = sc.get('factor_id_array') or [
                int(info.get('factor_id') or 0)
                for info in (sc.get('factor_info_array') or [])
                if int(info.get('factor_id') or 0)
            ]
            tree[tree_key] = {
                'card_id': lineage_card_id,
                'name': chara_map.get(str(lineage_card_id), f'Unknown ({lineage_card_id})') if lineage_card_id else '',
                'factors': get_factors(factor_ids, lineage_card_id) if lineage_card_id else [],
                'wins': get_win_summary(sc.get('win_saddle_id_array') or []),
            }
            if pos in (10, 20) and lineage_card_id:
                parent_card_ids.append(lineage_card_id)

        deck_support_ids = [
            int(item.get('support_card_id') or 0)
            for item in (row.get('support_card_list') or [])
            if int(item.get('support_card_id') or 0)
        ]
        deck_meta = _deck_meta_from_ids(deck_support_ids)

        out.append({
            'viewer_id': int(viewer_id),
            'trainer_name': summary.get('name', ''),
            'trained_chara_id': int(trained_chara_id),
            'card_id': int(card_id),
            'chara_name': chara_name,
            'rank': int(row.get('rank') or 0),
            'rank_score': int(row.get('rank_score') or 0),
            'scenario_id': int(row.get('scenario_id') or 0),
            'running_style': int(row.get('running_style') or 0),
            'talent_level': int(row.get('talent_level') or 0),
            'speed': int(row.get('speed') or 0),
            'stamina': int(row.get('stamina') or 0),
            'power': int(row.get('power') or 0),
            'guts': int(row.get('guts') or 0),
            'wiz': int(row.get('wiz') or 0),
            'aptitudes': get_trained_aptitudes(row),
            'wins': len(row.get('win_saddle_id_array') or []),
            'factors': factors,
            'tree': tree,
            'parent_card_ids': parent_card_ids,
            'deck_support_ids': deck_support_ids,
            'deck_support_cards': deck_meta['deck_support_cards'],
            'deck_type_counts': deck_meta['deck_type_counts'],
            'deck_archetype': deck_meta['deck_archetype'],
            'shared_support_card_id': int(summary.get('support_card_id') or 0),
        })

    out.sort(key=lambda v: (-v['rank_score'], -v['rank']))
    return out, 'ok'


def _base_chara_id(card_id):
    try:
        value = int(card_id or 0)
    except (TypeError, ValueError):
        return 0
    return affinity_calc.card_to_chara_id(value) if value > 0 else 0


def validate_start_selection(req):
    support_ids = [int(card_id) for card_id in req.support_card_ids]
    friend_card_id = int(req.friend_card_id)
    if friend_card_id in support_ids:
        return "Friend support card is already in selected deck"

    friend_info = support_map.get(str(friend_card_id), {})
    friend_name = normalize_card_name(friend_info.get('name'))
    if not friend_name:
        return None

    for support_id in support_ids:
        support_name = normalize_card_name(support_map.get(str(support_id), {}).get('name'))
        if support_name and support_name == friend_name:
            return "Friend support card has same character as selected deck"

    trainee_name = normalize_card_name(chara_map.get(str(req.card_id), ''))
    if trainee_name and trainee_name == friend_name:
        return "Friend support card has same character as trainee"

    parent1_cards = active_parent_cards.get(int(req.parent_id_1), [])
    parent2_cards = active_parent_cards.get(int(req.parent_id_2), [])
    trainee_base = _base_chara_id(req.card_id)
    direct_parent_cards = [
        cards[0]
        for cards in (parent1_cards, parent2_cards)
        if cards
    ]
    if trainee_base and any(
        _base_chara_id(card_id) == trainee_base
        for card_id in direct_parent_cards
    ):
        return "Selected direct parent is same character as trainee"

    return None


def deck_type_counts_from_ids(support_ids, friend_card_id=0):
    counts = [0] * 5
    for sid_int in list(support_ids or []) + ([friend_card_id] if friend_card_id else []):
        info = support_map.get(str(sid_int))
        if not info:
            continue
        ctype = info.get('type')
        if ctype == "Speed": counts[0] += 1
        elif ctype == "Stamina": counts[1] += 1
        elif ctype == "Power": counts[2] += 1
        elif ctype == "Guts": counts[3] += 1
        elif ctype == "Wisdom": counts[4] += 1
    return counts


def deck_type_counts_from_chara(chara_info):
    ids = []
    for card in (chara_info or {}).get('support_card_array') or []:
        sid = int(card.get('support_card_id') or 0)
        if sid:
            ids.append(sid)
    return deck_type_counts_from_ids(ids)


def apply_deck_type_counts(preset, req=None, chara_info=None):
    counts = None
    if req and (req.support_card_ids or req.friend_card_id):
        counts = deck_type_counts_from_ids(req.support_card_ids, req.friend_card_id)
    elif chara_info:
        counts = deck_type_counts_from_chara(chara_info)
    if counts is not None:
        preset["_deck_type_counts"] = counts
        scale_table = [0.0, 0.02, 0.05, 0.09, 0.14, 0.20]
        preset["_deck_multipliers"] = [1.0 + scale_table[min(5, c)] for c in counts]


def parent_rank_point(parent_id):
    parent = active_parent_rank_points.get(int(parent_id))
    if not parent:
        return 0
    rank = int(parent.get('rank') or 0)
    if rank == 13:
        return 62
    return int(parent.get('rank_score') or 0)


def selected_succession_rank_point(req):
    # Always use the account's total rank point balance (item 75), not per-parent sums
    # The API expects current_succession_rank_point = what the player currently has
    return active_start_state.get('succession_rank_point', 0)

skill_data = {}
skill_data_path = base_dir / 'data' / 'skill_data.json'
if skill_data_path.exists():
    with open(skill_data_path, 'r', encoding='utf-8') as f:
        skill_data = json.load(f)

factor_map = {}
factor_map_path = base_dir / 'data' / 'factor_map.json'
if factor_map_path.exists():
    with open(factor_map_path, 'r', encoding='utf-8') as f:
        factor_map = json.load(f)

race_map = {}
race_map_path = base_dir / 'data' / 'race_map.json'
if race_map_path.exists():
    with open(race_map_path, 'r', encoding='utf-8') as f:
        race_map = json.load(f)


def _independent_account():
    return _runtime_account_name() or _current_campaign_account()


def _independent_client(account):
    _assert_campaign_account(account)
    if active_client is None:
        raise WorkflowConflict("Login/load account first")
    return active_client


def _independent_dashboard():
    if active_dashboard_data is not None and not active_dashboard_data.get(
        "friendsLoaded"
    ):
        _refresh_dashboard_friend_supports()
    dashboard = active_dashboard_data or {}
    account = active_account or dashboard.get("account") or {}
    trainees = []
    for row in dashboard.get("umas") or []:
        if not isinstance(row, dict):
            continue
        card_id = int(row.get("card_id") or row.get("id") or 0)
        if not card_id:
            continue
        trainees.append({
            **dict(row),
            "card_id": card_id,
            "base_chara_id": _base_chara_id(card_id),
        })

    parents = []
    for row in dashboard.get("parents") or []:
        if not isinstance(row, dict):
            continue
        trained_chara_id = int(
            row.get("trained_chara_id")
            or row.get("instance_id")
            or row.get("id")
            or 0
        )
        card_id = int(row.get("card_id") or 0)
        if not trained_chara_id:
            continue
        parents.append({
            **dict(row),
            "trained_chara_id": trained_chara_id,
            "base_chara_id": _base_chara_id(card_id),
        })

    support_cards = []
    seen_supports = set()
    for row in dashboard.get("supports") or []:
        if not isinstance(row, dict):
            continue
        support_card_id = int(
            row.get("support_card_id")
            or row.get("card_id")
            or row.get("id")
            or 0
        )
        if not support_card_id or support_card_id in seen_supports:
            continue
        seen_supports.add(support_card_id)
        support_cards.append({
            **dict(row),
            "support_card_id": support_card_id,
        })
    selected_friend = active_selection.get("friend") or {}
    selected_friend_card_id = int(
        selected_friend.get("support_card_id")
        or selected_friend.get("card_id")
        or selected_friend.get("id")
        or 0
    )
    if selected_friend_card_id and selected_friend_card_id not in seen_supports:
        support_cards.append({
            "support_card_id": selected_friend_card_id,
            "name": selected_friend.get("name") or f"Support #{selected_friend_card_id}",
            "is_friend": True,
        })

    saved_race_agendas = []
    for preset in preset_store.read_all():
        races = list(preset.get("extra_race_list") or [])
        mandatory = list(preset.get("mandatory_race_list") or [])
        if races or mandatory:
            saved_race_agendas.append({
                "name": preset.get("name") or "Unnamed preset",
                "races": races,
                "mandatory_races": mandatory,
            })

    if isinstance(account, dict):
        account_label = account.get("name") or account.get("account")
    else:
        account_label = str(account or "")
    return {
        "account_label": account_label or _independent_account(),
        "trainees": trainees,
        "parents": parents,
        "support_cards": support_cards,
        "friend_supports": [
            dict(row) for row in dashboard.get("friends") or []
            if isinstance(row, dict)
        ],
        "decks": [dict(row) for row in dashboard.get("decks") or []],
        "saved_race_agendas": saved_race_agendas,
    }


def _independent_pre_start():
    """Return bootstrap metadata without consuming the start handshake.

    ``idle_single_mode/pre_start`` belongs immediately before
    ``idle_single_mode/start``.  Calling it while rendering the Independent
    page leaves a stale pre-start handshake behind before reconciliation can
    refresh account state.  The runner owns that mutating call instead.
    """
    if active_client is None:
        return {}
    cost_info = {
        "detected_tp_cost": None,
        "tp_cost_source": "",
        "tp_cost_error": "",
    }
    try:
        resolution = _independent_tp_cost(_independent_account())
        cost_info.update({
            "detected_tp_cost": resolution.cost,
            "tp_cost_source": resolution.source,
        })
    except Exception as exc:
        cost_info["tp_cost_error"] = str(exc)
    return {
        "reserved_race_info": [],
        "last_idle_single_mode_start_info": {},
        **cost_info,
    }


def _independent_busy_workflow():
    if career_runner.snapshot().get("running"):
        return "career"
    loop_thread = globals().get("backend_loop_thread")
    if loop_thread is not None and loop_thread.is_alive():
        return "career"
    career = (active_account or {}).get("career") or {}
    if career.get("active"):
        return "career"
    return None


def _independent_account_state(account):
    _assert_campaign_account(account)
    return {
        "tp_info": dict(
            active_start_state.get("tp_info")
            or getattr(active_client, "tp_info", {})
            or {}
        ),
        "current_money": int(active_start_state.get("current_money") or 0),
        "succession_rank_point": int(
            active_start_state.get("succession_rank_point") or 0
        ),
    }


def _independent_succession_rank_point(account, setup):
    _assert_campaign_account(account)
    parent_1 = active_parent_full.get(int(setup.get("parent_id_1") or 0))
    parent_2 = active_parent_full.get(int(setup.get("parent_id_2") or 0))
    if not parent_1 or not parent_2:
        raise ValueError("selected parents are unavailable for affinity")
    mdb_path = master_data.configured_master_mdb_path(base_dir)
    if not mdb_path or not Path(mdb_path).exists():
        raise ValueError("master.mdb is unavailable for affinity")
    affinity = affinity_calc.calculate_affinity(
        str(mdb_path),
        int(setup.get("card_id") or 0),
        parent_1,
        parent_2,
    )
    return int(affinity.get("total") or 0)


def _independent_refresh_account(account):
    _assert_campaign_account(account)
    client = _independent_client(account)
    response = client.call("load/index", {"adid": ""})
    data = (response or {}).get("data") or {}
    client.refresh_cached_account_state(data)
    _build_dashboard_from_login_response(response)
    return response


def _independent_load_progress(account):
    _assert_campaign_account(account)
    client = _independent_client(account)
    progress = (client.cached_load_data or {}).get(
        "idle_single_mode_load_info"
    ) or {}
    return dict(progress) if isinstance(progress, dict) else {}


def _independent_reauthenticate(account):
    _assert_campaign_account(account)
    print("[independent] session expired (201); re-authenticating...", flush=True)
    return auto_login_from_cache()


def _independent_recover_tp(account):
    _assert_campaign_account(account)
    client = _independent_client(account)
    response = client.recovery_tp(1)
    tp_info = (response or {}).get("data", {}).get("tp_info")
    if tp_info:
        active_start_state["tp_info"] = dict(tp_info)
    elif getattr(client, "tp_info", None):
        active_start_state["tp_info"] = dict(client.tp_info)
    return int(
        (active_start_state.get("tp_info") or {}).get("current_tp") or 0
    ) > 0


def _independent_tp_cost(account):
    _assert_campaign_account(account)
    client = _independent_client(account)
    common_define = (
        (client.cached_load_data or {}).get("common_define") or {}
    )
    return resolve_independent_training_tp_cost(
        master_data.configured_master_mdb_path(base_dir),
        base_cost=int(
            common_define.get("single_mode_trainer_point_use_value") or 0
        ),
        server_time=int(getattr(client, "last_server_time", 0) or 0),
    )


def _independent_race_array(setup):
    return canonicalize_start_race_array(base_dir, setup)


_independent_runtime_dir = runtime_output_root()
independent_store = IndependentTrainingStore(
    os.environ.get("SWEEPY_INDEPENDENT_DB")
    or _independent_runtime_dir / "independent_training.sqlite3"
)
workflow_job_store = SweepyJobStore(
    os.environ.get("SWEEPY_JOBS_DB")
    or _independent_runtime_dir / "control-plane.sqlite3"
)


def _independent_finalizer(account):
    return IndependentFinalizer(
        store=independent_store,
        client=_independent_client(account),
        skill_buyer=career_runner.skill_buyer,
        factor_map=factor_map,
    )


independent_runner = IndependentTrainingRunner(
    independent_store,
    client_provider=_independent_client,
    finalizer_provider=_independent_finalizer,
    account_state_provider=_independent_account_state,
    refresh_account=_independent_refresh_account,
    recover_tp=_independent_recover_tp,
    tp_cost_provider=_independent_tp_cost,
    race_array_provider=_independent_race_array,
    succession_rank_point_provider=_independent_succession_rank_point,
    load_progress_provider=_independent_load_progress,
    auth_recovery=_independent_reauthenticate,
    heartbeat_lease=lambda account: independent_service.heartbeat(),
    release_lease=lambda account: independent_service.release_lease(),
)
independent_service = IndependentTrainingService(
    independent_store,
    independent_runner,
    workflow_job_store,
    account_provider=_independent_account,
    dashboard_provider=_independent_dashboard,
    busy_workflow_provider=_independent_busy_workflow,
    pre_start_provider=_independent_pre_start,
)


def _assert_independent_training_idle():
    lease = workflow_job_store.get_workflow_lease(
        _independent_account()
    )
    runner_state = str(
        (independent_runner.snapshot() or {}).get("state") or ""
    )
    active_runner_states = {
        "STARTING",
        "RUNNING",
        "COLLECTING",
        "FINALIZING",
        "WAITING_FOR_TP",
        "NEEDS_ATTENTION",
    }
    if (
        lease
        and lease.get("workflow_type") == "independent_training"
    ) or runner_state in active_runner_states:
        raise HTTPException(
            status_code=409,
            detail="Independent Training is active on this dashboard instance",
        )


def skill_entry_name(entry):
    if isinstance(entry, dict):
        return entry.get("name") or ""
    return entry

def get_win_summary(win_saddle_ids):
    summary = {
        "g1": 0,
        "g2": 0,
        "g3": 0
    }

    g1_saddle_ids = set()
    try:
        mdb_path = master_data.configured_master_mdb_path(base_dir)
        if mdb_path and Path(mdb_path).exists():
            g1_saddle_ids = set(affinity_calc._load_g1_saddles(str(mdb_path)))
    except Exception:
        g1_saddle_ids = set()

    # Current race_map.json is keyed by meta/program/instance, while
    # win_saddle_id_array contains single_mode_wins_saddle IDs.  Keep the old
    # flat-map fallback for legacy fixtures, but use master.mdb for G1 trophies.
    legacy_race_map = race_map
    if isinstance(race_map, dict) and any(key in race_map for key in ("meta", "program", "instance")):
        legacy_race_map = {}

    for saddle_id in win_saddle_ids or []:
        try:
            normalized_saddle_id = int(saddle_id)
        except (TypeError, ValueError):
            normalized_saddle_id = saddle_id

        if normalized_saddle_id in g1_saddle_ids:
            summary["g1"] += 1
            continue

        race = legacy_race_map.get(str(saddle_id)) if isinstance(legacy_race_map, dict) else None
        grade = race.get("grade") if race else None
        if grade == "G1":
            summary["g1"] += 1
        elif grade == "G2":
            summary["g2"] += 1
        elif grade == "G3":
            summary["g3"] += 1

    summary["total"] = summary["g1"] + summary["g2"] + summary["g3"]
    return summary

def clean_factor_name(name, base_id=None, category=None):
    if not isinstance(name, str):
        return name

    if category == "skill" and "?" in name and base_id is not None:
        skill_name = skill_entry_name(skill_data.get(f"{base_id}2"))
        if skill_name:
            return skill_name
    return name.replace(" ?", " ○")

def get_factors(fid_array, owner_card_id=None):
    results = []
    category_order = {
        "stat": 0,
        "aptitude": 1,
        "unique": 2,
        "race": 3,
        "skill": 4,
        "scenario": 5,
        "other": 6
    }
    stat_map = {
        1: 'Speed', 2: 'Stamina', 3: 'Power', 4: 'Guts', 5: 'Wit',
        11: 'Turf', 12: 'Dirt',
        21: 'Short', 22: 'Mile', 23: 'Medium', 24: 'Long',
        31: 'Front Runner', 32: 'Pace Chaser', 33: 'Late Surger', 34: 'End Closer'
    }
    
    owner_cid_str = str(owner_card_id) if owner_card_id else ""
    if len(owner_cid_str) > 4: owner_cid_str = owner_cid_str[:4]

    for fid in fid_array:
        if not fid or fid <= 0: continue

        fid_str = str(fid)
        factor_info = factor_map.get(fid_str)
        if factor_info:
            base_id = fid // 100
            category = factor_info.get("category", "other")
            name = clean_factor_name(factor_info.get("name", f"Unknown({fid})"), base_id, category)
            stars = factor_info.get("stars", fid % 100)
            results.append({"name": name, "stars": stars, "id": fid, "category": category})
            continue

        base_id = fid // 100
        stars = fid % 100
        bid_str = str(base_id)
        name = f"Unknown({base_id})"
        category = "other"
        
        if base_id <= 34:
            category = "stat" if base_id <= 5 else "aptitude"
            name = stat_map.get(base_id, name)
        
        elif bid_str in skill_data:
            category = "skill"
            name = skill_entry_name(skill_data[bid_str])
            
        results.append({"name": name, "stars": stars, "id": base_id, "category": category})

    return [
        factor for _, factor in sorted(
            enumerate(results),
            key=lambda item: (category_order.get(item[1]["category"], 99), item[0])
        )
    ]


def get_chara_factor_ids(chara):
    factor_ids = chara.get('factor_id_array')
    if isinstance(factor_ids, list) and factor_ids:
        return factor_ids
    return [f.get('factor_id', 0) for f in chara.get('factor_info_array', [])]


def get_trained_skill_ids(chara):
    ids = []
    for key in ('skill_id_array', 'skill_tips_id_array'):
        values = chara.get(key)
        if isinstance(values, list):
            ids.extend(int(v) for v in values if v)
    for key in ('skill_array', 'skill_tips_array', 'skill_info_array'):
        for item in chara.get(key) or []:
            if isinstance(item, dict):
                sid = item.get('skill_id') or item.get('id')
                if sid:
                    ids.append(int(sid))
    seen = set()
    out = []
    for sid in ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def get_skill_names(skill_ids):
    out = []
    for sid in skill_ids or []:
        entry = skill_data.get(str(sid)) or skill_data.get(str(int(sid) // 10))
        out.append({'id': int(sid), 'name': skill_entry_name(entry) or f'Unknown({sid})'})
    return out


def get_trained_stats(chara):
    return {
        'speed': int(chara.get('speed') or 0),
        'stamina': int(chara.get('stamina') or 0),
        'power': int(chara.get('power') or 0),
        'guts': int(chara.get('guts') or 0),
        'wit': int(chara.get('wiz') or chara.get('wit') or 0),
    }


def get_trained_aptitudes(chara):
    return {
        'turf': int(chara.get('proper_ground_turf') or 0),
        'dirt': int(chara.get('proper_ground_dirt') or 0),
        'sprint': int(chara.get('proper_distance_short') or 0),
        'mile': int(chara.get('proper_distance_mile') or 0),
        'medium': int(chara.get('proper_distance_middle') or 0),
        'long': int(chara.get('proper_distance_long') or 0),
    }


def get_trained_style_aptitudes(chara):
    """Running-style aptitudes, in the order career_bot.dailies.best_running_style ranks them."""
    return {
        'front': int(chara.get('proper_running_style_nige') or 0),
        'pace': int(chara.get('proper_running_style_senko') or 0),
        'late': int(chara.get('proper_running_style_sashi') or 0),
        'end': int(chara.get('proper_running_style_oikomi') or 0),
    }


def get_item_count(item_list, item_id):
    for item in item_list or []:
        if item.get('item_id') == item_id:
            return item.get('number', 0)
    return 0



def _factor_goal_hits(parent, goal):
    want = {str(goal.get('distance') or '').lower(), str(goal.get('surface') or '').lower()}
    want.discard('')
    hits = []
    score = 0
    for node_key in ('self', 'p1', 'p2'):
        node = (parent.get('tree') or {}).get(node_key) or {}
        for f in node.get('factors') or []:
            name = str(f.get('name') or '')
            stars = int(f.get('stars') or 0)
            if any(w in name.lower() for w in want):
                score += 8 + stars * 3
                hits.append({'name': name, 'stars': stars, 'source': node_key})
    return score, hits

def _normalized_factor_name(value):
    return re.sub(r'[^a-z0-9]+', '', str(value or '').strip().lower())


def _self_factor_stars(parent, factor_name):
    wanted = _normalized_factor_name(factor_name)
    if not wanted:
        return 0
    node = ((parent.get('tree') or {}).get('self') or {}) if isinstance(parent, dict) else {}
    best = 0
    for factor in node.get('factors') or []:
        if not isinstance(factor, dict):
            continue
        category = str(factor.get('category') or '').strip().lower()
        if category and category not in {'stat', 'blue'}:
            continue
        if _normalized_factor_name(factor.get('name')) != wanted:
            continue
        try:
            best = max(best, int(factor.get('stars') or 0))
        except (TypeError, ValueError):
            continue
    return best


def _direct_lineage_target_evidence(p1, p2, goal):
    rows = goal.get('target_factors') if isinstance(goal, dict) else []
    evidence = []
    score = 0
    feasible = True
    for target in rows or []:
        if not isinstance(target, dict):
            continue
        if str(target.get('scope') or '').strip().lower() != 'lineage':
            continue
        if str(target.get('aggregation') or '').strip().lower() != 'sum':
            continue
        if str(target.get('lineage_depth') or '').strip().lower() != 'direct':
            continue
        name = str(target.get('name') or '').strip().lower()
        if not name:
            continue
        try:
            required = int(target.get('minimum_stars') or 0)
        except (TypeError, ValueError):
            required = 0
        parent1_stars = _self_factor_stars(p1, name)
        parent2_stars = _self_factor_stars(p2, name)
        maximum_candidate_stars = 3
        maximum_total = parent1_stars + parent2_stars + maximum_candidate_stars
        matched = maximum_total >= required
        if bool(target.get('required', True)) and not matched:
            feasible = False
        score += (parent1_stars + parent2_stars) * 25
        evidence.append({
            'name': name,
            'required_stars': required,
            'parent1_stars': parent1_stars,
            'parent2_stars': parent2_stars,
            'maximum_candidate_stars': maximum_candidate_stars,
            'maximum_total_stars': maximum_total,
            'feasible': matched,
        })
    return score, evidence, feasible


def _shared_races_for_setup(p1, p2):
    wins = []
    for p in (p1, p2):
        for node in (p.get('tree') or {}).values():
            for w in node.get('wins') or []:
                if isinstance(w, dict):
                    wins.append(str(w.get('name') or w.get('id') or 'Race'))
                else:
                    wins.append(str(w))
    counts = {}
    for w in wins:
        if w and w != '0': counts[w] = counts.get(w, 0) + 1
    races = [{'name': k, 'count': v} for k, v in counts.items() if v > 1]
    races.sort(key=lambda r: (-r['count'], r['name']))
    return races

def _compat_tier(total):
    if total > 150: return '◎'
    if total >= 50: return '◯'
    return '△'

def _pool_parents(pool):
    owned = list((active_dashboard_data or {}).get('parents') or [])
    for p in owned: p['source'] = 'owned'
    vets = list((active_dashboard_data or {}).get('friendVeterans') or [])
    for v in vets:
        v['source'] = 'veteran'
        if 'instance_id' not in v:
            v['instance_id'] = v.get('trained_chara_id') or v.get('id')
    if pool == 'owned': return owned
    if pool == 'veteran': return vets
    return owned + vets

def get_account_status(data, career_data=None):
    tp_info = data.get('tp_info') or (active_client.tp_info if active_client else {})
    coin_info = data.get('coin_info') or (active_client.coin_info if active_client else {})
    item_list = data.get('item_list') or data.get('user_item_array')
    if item_list is None:
        gold = active_client.item_map.get(59, 0) if active_client else 0
    else:
        gold = get_item_count(item_list, 59)
    career = data.get('single_mode_chara_light') or None

    if career_data:
        career_payload = career_data.get('data') if career_data.get('data') else career_data
        if career_payload.get('chara_info'):
            career = career_payload.get('chara_info')

    status = {
        "tp": {
            "current": tp_info.get('current_tp', 0),
            "max": tp_info.get('max_tp', 0)
        },
        "carrots": {
            "free": coin_info.get('fcoin', 0) or 0,
            "paid": coin_info.get('coin', 0) or 0,
            "total": (coin_info.get('fcoin', 0) or 0) + (coin_info.get('coin', 0) or 0)
        },
        "gold": gold,
        "clocks": active_client.item_map.get(95, 0) if active_client else 0,
        "career": None
    }
    if career:
        card_id = str(career.get('card_id', ''))
        
        p1 = career.get('succession_trained_chara_id_1')
        p2 = career.get('succession_trained_chara_id_2')
        rental = career.get('rental_succession_trained_chara') or {}
        rental_viewer_id = rental.get('viewer_id')
        rental_trained_chara_id = rental.get('trained_chara_id')

        friend_viewer_id = None
        friend_card_id = None
        friend_support = None
        current_deck_cards = []
        current_deck_supports = []
        
        support_array = career.get('support_card_array') or []
        for sc in support_array:
            pos = sc.get('position')
            if pos == 6:
                friend_viewer_id = sc.get('owner_viewer_id')
                friend_card_id = sc.get('support_card_id')
                friend_info = support_map.get(str(friend_card_id))
                friend_support = {
                    "viewer_id": friend_viewer_id,
                    "support_card_id": friend_card_id,
                    "support_name": friend_info['name'] if friend_info else f"Unknown ({friend_card_id})",
                    "rarity": friend_info['rarity'] if friend_info else "?",
                    "type": display_support_type(friend_info['type']) if friend_info else "?",
                    "limit_break_count": sc.get('limit_break_count')
                }
            elif 1 <= pos <= 5:
                support_card_id = sc.get('support_card_id')
                current_deck_cards.append(support_card_id)
                support_info = support_map.get(str(support_card_id))
                current_deck_supports.append({
                    "id": str(support_card_id),
                    "name": support_info['name'] if support_info else f"Unknown ({support_card_id})",
                    "rarity": support_info['rarity'] if support_info else "?",
                    "type": display_support_type(support_info['type']) if support_info else "?"
                })

        matched_deck_id = None
        user_decks = data.get('support_card_deck_array') or []
        if current_deck_cards:
            current_deck_set = set(current_deck_cards)
            for deck in user_decks:
                deck_cards = deck.get('support_card_id_array') or []
                if set(deck_cards) == current_deck_set:
                    matched_deck_id = deck.get('deck_id')
                    break

        status["career"] = {
            "active": True,
            "card_id": card_id,
            "name": chara_map.get(card_id, f"Unknown ({card_id})"),
            "turn": career.get('turn', 0),
            "scenario_id": career.get('scenario_id', 0),
            "fans": career.get('fans', 0),
            "vital": career.get('vital', 0),
            "max_vital": career.get('max_vital', 0),
            "deck_id": matched_deck_id,
            "support_card_ids": current_deck_cards,
            "support_cards": current_deck_supports,
            "friend_viewer_id": friend_viewer_id,
            "friend_card_id": friend_card_id,
            "friend": friend_support,
            "parent_id_1": p1,
            "parent_id_2": p2,
            "rental_viewer_id": rental_viewer_id,
            "rental_trained_chara_id": rental_trained_chara_id,
        }

    return status




class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""
    code: str = ""
    steam_id: str = ""
    steam_session_ticket: str = ""

class DeleteCareerRequest(BaseModel):
    current_turn: int = 0

class StartCareerRequest(BaseModel):
    card_id: int
    support_card_ids: list[int]
    friend_viewer_id: int
    friend_card_id: int
    parent_id_1: int
    parent_id_2: int
    scenario_id: int = 4
    deck_id: int = 1
    use_tp: int = 30
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    burn_clocks: bool = False

RUNTIME_PRESET_OVERRIDE_KEYS = frozenset({
    "scenario_id",
    "scenario",
    "parent_run",
    "tp_mode",
    "extra_race_list",
    "mandatory_race_list",
})


def apply_runtime_preset_overrides(preset, overrides):
    merged = dict(preset or {})
    if not isinstance(overrides, dict):
        return merged
    for key in RUNTIME_PRESET_OVERRIDE_KEYS:
        if key not in overrides:
            continue
        value = overrides[key]
        if isinstance(value, list):
            value = list(value)
        elif isinstance(value, dict):
            value = dict(value)
        merged[key] = value
    return merged


class RunCareerRequest(BaseModel):
    card_id: int = 0
    support_card_ids: list[int] = []
    friend_viewer_id: int = 0
    friend_card_id: int = 0
    parent_id_1: int = 0
    parent_id_2: int = 0
    rental_viewer_id: int = 0
    rental_trained_chara_id: int = 0
    scenario_id: int = 0
    deck_id: int = 1
    use_tp: int = 30
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    preset_name: str = ""
    max_steps: int = 2500
    burn_clocks: bool = False
    dev_mode: bool = True
    stop_on_empty_tp: bool = False
    run_delay_min_min: int = 0
    run_delay_max_min: int = 0
    tp_mode: str = "carat"
    preset_overrides: dict = Field(default_factory=dict)

class SaveRacesRequest(BaseModel):
    preset_name: str
    races: list[int]
    mandatory_races: list[int] = []

class SavePresetRequest(BaseModel):
    preset: dict

class RenamePresetRequest(BaseModel):
    old_name: str
    new_name: str

class DuplicatePresetRequest(BaseModel):
    source_name: str
    new_name: str

class DeletePresetByNameRequest(BaseModel):
    name: str

class CareerActionRequest(BaseModel):
    command_type: int
    command_id: int
    current_turn: int
    current_vital: int
    command_group_id: int = 0
    select_id: int = 0

class TpRefillRequest(BaseModel):
    count: int = 1

class FriendListRequest(BaseModel):
    exclude_viewer_ids: list[int] = []
    force_refresh: bool = False

class FriendManageRequest(BaseModel):
    viewer_id: int

class VeteranRemoveRequest(BaseModel):
    trained_chara_id_array: list[int] = []

class SupportDeckUpdateRequest(BaseModel):
    deck_id: int
    name: str = Field(default="", max_length=32)
    support_card_ids: list[int] = []

class AdvisorRequest(BaseModel):
    trainee_card_id: int = 0
    running_style: int = 0

class ApiDelayRequest(BaseModel):
    min: float = 1.6
    max: float = 4.0
    disabled: bool = False

class MasterDataPathRequest(BaseModel):
    master_mdb_path: str

class DailiesRunRequest(BaseModel):
    team_trials: bool = False
    daily_races: bool = False
    legend_races: bool = False
    daily_shop: bool = False
    trained_chara_id: int = 0
    opponent_strength: int = 1
    legend_race_id: int = 0


class InheritanceRecommendRequest(BaseModel):
    target_card_id: int
    pool: str = "both"
    goal: dict = Field(default_factory=dict)
    limit: int = 10

    @field_validator("pool")
    @classmethod
    def validate_pool(cls, value):
        normalized = str(value or "both").strip().lower()
        if normalized not in {"owned", "veteran", "both"}:
            raise ValueError("pool must be owned, veteran, or both")
        return normalized

    @field_validator("limit")
    @classmethod
    def clamp_limit(cls, value):
        return max(1, min(int(value or 10), 50))

class CampaignFinalParentsRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: str | None = Field(default=None, min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    final_uma_card_id: int = Field(gt=0)
    spark_targets: list[CampaignSparkTarget] = Field(default_factory=list)
    limit: int = Field(default=3, ge=1, le=50)

class CampaignLoopRecommendationRequest(CampaignFinalParentsRecommendationRequest):
    final_parent_chara_id: int = Field(gt=0)
    pinned_chara_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list)

class CampaignBootstrapRecommendationRequest(CampaignFinalParentsRecommendationRequest):
    pinned_chara_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list)

class CampaignCreateRequest(BaseModel):
    spec: ParentCampaignSpec

class CampaignApproveRunRequest(BaseModel):
    selection_override: dict | None = None

class CampaignSelectCandidateRequest(BaseModel):
    candidate_id: str

class CampaignCancelRequest(BaseModel):
    reason: str = ""


def _independent_api_call(method, *args, **kwargs):
    try:
        return method(*args, **kwargs)
    except (RunNotFound, PresetNotFound) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        WorkflowConflict,
        InvalidRunTransition,
        RunVersionConflict,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/independent-training/bootstrap")
async def independent_training_bootstrap():
    return _independent_api_call(independent_service.bootstrap)


@app.get("/api/independent-training/presets")
async def list_independent_training_presets():
    return {"presets": _independent_api_call(independent_service.list_presets)}


@app.post("/api/independent-training/presets")
async def save_independent_training_preset(req: IndependentTrainingPreset):
    return _independent_api_call(
        independent_service.save_preset,
        req.name,
        req.setup.model_dump(mode="json"),
        count=req.count,
        tp_mode=req.tp_mode.value,
    )


@app.get("/api/independent-training/presets/{name}")
async def get_independent_training_preset(name: str):
    return _independent_api_call(independent_service.get_preset, name)


@app.delete("/api/independent-training/presets/{name}")
async def delete_independent_training_preset(name: str):
    return _independent_api_call(independent_service.delete_preset, name)


@app.get("/api/independent-training/trainees/{card_id}/objective-races")
async def independent_training_objective_races(card_id: int):
    dashboard = _independent_dashboard()
    if card_id not in {
        int(row.get("card_id") or 0)
        for row in dashboard.get("trainees") or []
    }:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown trainee card {card_id}",
        )
    programs = {
        int(program_id): dict(row)
        for program_id, row in (race_map.get("program") or {}).items()
    }
    objectives = CareerObjectiveResolver(
        base_dir,
        programs,
    ).specific_race_objectives(_base_chara_id(card_id))
    return {
        "card_id": card_id,
        "objective_races": [
            {
                "turn": objective.deadline_turn,
                "program_id": objective.condition_id,
                "name": programs[objective.condition_id].get("name") or "",
            }
            for objective in objectives
            if objective.deadline_turn > 0
            and objective.condition_id in programs
        ],
    }


@app.post("/api/independent-training/runs")
async def enqueue_independent_training_runs(req: EnqueueRuns):
    return _independent_api_call(
        independent_service.enqueue,
        req.setup.model_dump(mode="json"),
        count=req.count,
        tp_mode=req.tp_mode.value,
    )


@app.post("/api/independent-training/start", status_code=202)
async def start_independent_training():
    return _independent_api_call(independent_service.start, clear_stop=True)


@app.get("/api/independent-training/status")
async def independent_training_status():
    return _independent_api_call(independent_service.status)


@app.post("/api/independent-training/stop-after-current")
async def stop_independent_training_after_current():
    return _independent_api_call(
        independent_service.stop_after_current
    )


@app.post("/api/independent-training/resume", status_code=202)
async def resume_independent_training():
    return _independent_api_call(independent_service.resume)


@app.delete("/api/independent-training/runs/{run_id}")
async def cancel_independent_training_run(run_id: str):
    return _independent_api_call(independent_service.cancel, run_id)


@app.post("/api/independent-training/adopt-server-run", status_code=202)
async def adopt_independent_training_server_run():
    return _independent_api_call(independent_service.adopt_server_run)


@app.post("/api/independent-training/runs/{run_id}/discard")
async def discard_independent_training_run(run_id: str):
    return _independent_api_call(
        independent_service.discard,
        run_id,
        reason="discarded from dashboard",
    )


@app.post("/api/independent-training/reconcile", status_code=202)
async def reconcile_independent_training():
    return _independent_api_call(independent_service.reconcile)


@app.post("/api/inheritance/recommend")
async def inheritance_recommend(req: InheritanceRecommendRequest):
    if not active_dashboard_data:
        return {"success": False, "detail": "Login/load account first"}
    target_base_chara_id = _base_chara_id(req.target_card_id)
    all_parents = [p for p in _pool_parents(req.pool) if p.get('tree')]
    parents = []
    excluded_same_as_trainee = 0
    for parent in all_parents:
        parent_base = _base_chara_id(parent.get('card_id'))
        if target_base_chara_id and parent_base == target_base_chara_id:
            excluded_same_as_trainee += 1
            continue
        parents.append(parent)
    results = []
    excluded_same_parent_character_pairs = 0
    excluded_factor_infeasible_pairs = 0
    mdb = master_data.status(base_dir).get('master_mdb_path')
    for i, p1 in enumerate(parents):
        for p2 in parents[i+1:]:
            p1_base = _base_chara_id(p1.get('card_id'))
            p2_base = _base_chara_id(p2.get('card_id'))
            if p1_base and p1_base == p2_base:
                excluded_same_parent_character_pairs += 1
                continue
            compat = {'total': 0, 'race_compat': 0}
            if mdb and p1.get('source') == 'owned' and p2.get('source') == 'owned':
                raw1 = active_parent_full.get(int(p1.get('instance_id') or 0))
                raw2 = active_parent_full.get(int(p2.get('instance_id') or 0))
                if raw1 and raw2:
                    try:
                        compat = affinity_calc.calculate_affinity(mdb, req.target_card_id, raw1, raw2)
                    except Exception:
                        compat = {'total': 0, 'race_compat': 0}
            s1, h1 = _factor_goal_hits(p1, req.goal or {})
            s2, h2 = _factor_goal_hits(p2, req.goal or {})
            target_factor_score, target_factor_evidence, target_factor_feasible = (
                _direct_lineage_target_evidence(p1, p2, req.goal or {})
            )
            if not target_factor_feasible:
                excluded_factor_infeasible_pairs += 1
                continue
            races = _shared_races_for_setup(p1, p2)
            race_score = min(40, sum(r['count'] for r in races) * 2)
            score = (
                (compat.get('total') or 0) * 0.45
                + s1
                + s2
                + target_factor_score
                + race_score
                + (int(p1.get('rank_score') or 0) + int(p2.get('rank_score') or 0)) / 20000
            )
            results.append({
                'parent1': {
                    'id': p1.get('instance_id'),
                    'card_id': p1.get('card_id'),
                    'base_chara_id': p1_base,
                    'name': p1.get('name'),
                    'source': p1.get('source'),
                },
                'parent2': {
                    'id': p2.get('instance_id'),
                    'card_id': p2.get('card_id'),
                    'base_chara_id': p2_base,
                    'name': p2.get('name'),
                    'source': p2.get('source'),
                },
                'score': score,
                'compat_total': compat.get('total') or 0,
                'compat_tier': _compat_tier(compat.get('total') or 0),
                'race_score': race_score,
                'races': races[:8],
                'spark_hits': (h1 + h2)[:12],
                'target_factor_feasible': target_factor_feasible,
                'target_factor_evidence': target_factor_evidence,
            })
    results.sort(key=lambda x: x['score'], reverse=True)
    limit = max(1, min(int(req.limit or 10), 50))
    for idx, row in enumerate(results[:limit], 1):
        row['rank'] = idx
    return {
        'success': True,
        'target_card_id': int(req.target_card_id),
        'target_base_chara_id': target_base_chara_id,
        'parent_count': len(parents),
        'excluded_same_as_trainee': excluded_same_as_trainee,
        'excluded_same_parent_character_pairs': excluded_same_parent_character_pairs,
        'excluded_factor_infeasible_pairs': excluded_factor_infeasible_pairs,
        'results': results[:limit],
    }

@app.get("/api/settings/turn-delay")
async def get_turn_delay_settings():
    return get_turn_delay()

@app.post("/api/settings/turn-delay")
async def set_turn_delay_settings(req: ApiDelayRequest):
    return set_turn_delay(req.min, req.max, req.disabled)

@app.get("/api/master-data/status")
async def master_data_status():
    return master_data.status(base_dir)

@app.post("/api/master-data/path")
async def set_master_data_path(req: MasterDataPathRequest):
    status = master_data.set_master_mdb_path(base_dir, req.master_mdb_path)
    if status.get("exists"):
        result = master_data.generate(base_dir)
        if result.get("success"):
            status["generated"] = result.get("generated", [])
        else:
            status["generation_error"] = result.get("detail") or "master_data generation failed"
    return status

@app.post("/api/master-data/generate")
async def generate_master_data():
    result = master_data.generate(base_dir)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "master_data generation failed")
    return result

@app.post("/api/presets/save_races")
async def save_races(req: SaveRacesRequest):
    preset = preset_store.read_one(req.preset_name)
    if not preset:
        return {"success": False, "detail": f"{req.preset_name} preset missing"}
    preset["extra_race_list"] = req.races
    preset["mandatory_race_list"] = req.mandatory_races
    preset_store.write(preset)
    return {"success": True}

@app.get("/api/presets")
async def get_presets():
    return {"success": True, "presets": preset_store.read_all()}

@app.post("/api/presets")
async def save_preset(req: SavePresetRequest):
    return {"success": True, "preset": preset_store.write(req.preset)}

@app.post("/api/presets/rename")
async def rename_preset(req: RenamePresetRequest):
    original = preset_store.read_one(req.old_name)
    if original is None:
        return {"success": False, "detail": f"Preset not found: {req.old_name}"}

    try:
        renamed = preset_store.rename(req.old_name, req.new_name)
    except PresetStoreError as exc:
        return {"success": False, "detail": str(exc)}

    if renamed["name"].casefold() == original["name"].casefold():
        return {"success": True, "preset": renamed, "campaigns_updated": 0}

    try:
        campaigns_updated = campaign_store.rename_preset_references(
            original["name"], renamed["name"]
        )
    except Exception as exc:
        try:
            preset_store.rename(renamed["name"], original["name"])
        except Exception as rollback_exc:
            return {
                "success": False,
                "detail": (
                    f"Campaign cascade failed: {exc}; "
                    f"preset rollback failed: {rollback_exc}"
                ),
            }
        return {"success": False, "detail": f"Campaign cascade failed: {exc}"}

    return {
        "success": True,
        "preset": renamed,
        "campaigns_updated": campaigns_updated,
    }

@app.post("/api/presets/duplicate")
async def duplicate_preset(req: DuplicatePresetRequest):
    try:
        duplicated = preset_store.duplicate(req.source_name, req.new_name)
    except PresetStoreError as exc:
        return {"success": False, "detail": str(exc)}
    return {"success": True, "preset": duplicated}

@app.post("/api/presets/delete")
async def delete_preset(req: DeletePresetByNameRequest):
    return {"success": preset_store.delete(req.name)}

def _campaign_api_call(method, *args):
    try:
        return method(*args)
    except CampaignNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CampaignError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.get("/api/campaigns")
async def list_campaigns(account: str | None = None):
    resolved_account = account if account is not None else _current_campaign_account()
    _assert_campaign_account(resolved_account)
    return {"success": True, "account": resolved_account, "campaigns": _campaign_api_call(campaign_service.list_campaigns, resolved_account)}

@app.post("/api/campaigns/recommend-final-parents")
async def recommend_campaign_final_parents(req: CampaignFinalParentsRecommendationRequest):
    payload = req.model_dump(mode="json")
    return {"success": True, "recommendation": _campaign_api_call(campaign_service.recommend_final_parents, payload)}

@app.post("/api/campaigns/recommend-loop")
async def recommend_campaign_loop(req: CampaignLoopRecommendationRequest):
    payload = req.model_dump(mode="json")
    return {"success": True, "recommendation": _campaign_api_call(campaign_service.recommend_loops, payload)}

@app.post("/api/campaigns/recommend-bootstraps")
async def recommend_campaign_bootstraps(req: CampaignBootstrapRecommendationRequest):
    payload = req.model_dump(mode="json")
    return {"success": True, "recommendation": _campaign_api_call(campaign_service.recommend_bootstraps, payload)}

@app.post("/api/campaigns")
async def create_campaign(req: CampaignCreateRequest):
    return {"success": True, "campaign": _campaign_api_call(campaign_service.create_campaign, req.spec)}

@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    return {"success": True, "campaign": _campaign_api_call(campaign_service.get_campaign, campaign_id)}

@app.post("/api/campaigns/{campaign_id}/activate")
async def activate_campaign(campaign_id: str):
    _assert_independent_training_idle()
    return {"success": True, "campaign": _campaign_api_call(campaign_service.activate, campaign_id)}

@app.post("/api/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: str):
    return {"success": True, "campaign": _campaign_api_call(campaign_service.pause, campaign_id)}

@app.post("/api/campaigns/{campaign_id}/resume")
async def resume_campaign(campaign_id: str):
    return {"success": True, "campaign": _campaign_api_call(campaign_service.resume, campaign_id)}

@app.post("/api/campaigns/{campaign_id}/advance")
async def advance_campaign(campaign_id: str):
    _assert_independent_training_idle()
    return {"success": True, "result": _campaign_api_call(_campaign_advance, campaign_id)}


@app.post("/api/campaigns/{campaign_id}/prepare-next-run")
async def prepare_campaign_next_run(campaign_id: str):
    return {"success": True, "result": _campaign_api_call(campaign_service.prepare_next_run, campaign_id)}

@app.post("/api/campaigns/{campaign_id}/approve-run")
async def approve_campaign_run(campaign_id: str, req: CampaignApproveRunRequest):
    return {"success": True, "result": _campaign_api_call(campaign_service.approve_run, campaign_id, req.selection_override)}

@app.post("/api/campaigns/{campaign_id}/select-candidate")
async def select_campaign_candidate(campaign_id: str, req: CampaignSelectCandidateRequest):
    return {"success": True, "result": _campaign_api_call(campaign_service.select_candidate, campaign_id, req.candidate_id)}

@app.post("/api/campaigns/{campaign_id}/continue-preferred")
async def continue_campaign_preferred(campaign_id: str):
    return {"success": True, "campaign": _campaign_api_call(campaign_service.continue_for_preferred, campaign_id)}

@app.post("/api/campaigns/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: str, req: CampaignCancelRequest):
    return {"success": True, "campaign": _campaign_api_call(campaign_service.cancel, campaign_id, req.reason)}

@app.get("/api/skills")
async def get_skills():
    current_skill_data = {}
    path = base_dir / 'data' / 'skill_data.json'
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            current_skill_data = json.load(f)
    return {"success": True, "skills": current_skill_data}

def start_career_from_request(req):
    global active_account, active_dashboard_data, active_support_card_deck_array
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    if active_account and active_account.get("career") and active_account["career"].get("active"):
         return {"success": False, "detail": "Cannot start a new career while another is active"}

    if not req.friend_viewer_id or not req.friend_card_id:
        return {"success": False, "detail": "Friend support card is required"}
    
    selection_error = validate_start_selection(req)
    if selection_error:
        return {"success": False, "detail": selection_error}

    # load/index returns full item list (read_info/index doesn't)
    for _load_attempt in range(2):
        try:
            res = active_client.call('load/index', {'adid': ''})
            data = res.get('data', {})
            active_client.refresh_cached_account_state(data)
            update_start_state(data)
            if active_account:
                active_account = get_account_status(data)
                if active_dashboard_data:
                    active_dashboard_data["account"] = active_account
            break
        except Exception as e:
            err_str = str(e)
            if _load_attempt == 0 and ("201" in err_str or "394" in err_str):
                if "201" in err_str:
                    print(f"[start_career] session expired (201) on load/index, re-authing...", flush=True)
                    if auto_login_from_cache():
                        print(f"[start_career] re-auth OK, retrying load/index", flush=True)
                        continue
                else:
                    print(f"[start_career] load/index busy (394), retrying...", flush=True)
                    import time
                    time.sleep(2.0)
                    continue
            print(f"[start_career] load/index refresh failed: {e}", flush=True)
            break

    if not active_start_state.get('tp_info'):
        return {"success": False, "detail": "Missing live TP state; login again before starting career"}
    if 'current_money' not in active_start_state:
        return {"success": False, "detail": "Missing live item state; login again before starting career"}

    tp_info = active_start_state['tp_info']
    current_tp = int(tp_info.get('current_tp') or 0)
    tp_action = decide_tp_action(
        req.use_tp, current_tp,
        getattr(req, 'tp_mode', 'carat'),
        getattr(req, 'stop_on_empty_tp', False),
    )
    if tp_action == "stop":
        return {"success": False, "detail": "TP_EXHAUSTED", "current_tp": current_tp}
    if tp_action == "wait":
        return {"success": False, "detail": "TP_REGEN_WAIT",
                "current_tp": current_tp, "use_tp": req.use_tp}
    if tp_action == "carat":
        for attempt in range(3):
            try:
                needed = ((req.use_tp - current_tp) + 29) // 30
                active_client.recovery_tp(needed)
                tp_info = active_client.tp_info
                active_start_state['tp_info'] = tp_info
                current_tp = int(tp_info.get('current_tp') or 0)
                if current_tp >= req.use_tp:
                    break
            except Exception as e:
                if "213" in str(e):
                    try:
                        res = active_client.call("load/index", {"adid": ""})
                        active_client.refresh_cached_account_state(res.get("data", {}))
                    except Exception:
                        pass
                dna_sleep(1.0, 1.0)

        if req.use_tp and current_tp < req.use_tp:
            return {"success": False, "detail": f"Not enough TP: {current_tp}/{req.use_tp}"}
    current_money = active_start_state['current_money']
    p1_rank = active_parent_rank_points.get(int(req.parent_id_1))
    p2_rank = active_parent_rank_points.get(int(req.parent_id_2))
    succession_rank_point = 0
    computed_affinity = None
    try:
        p1_full = active_parent_full.get(int(req.parent_id_1))
        p2_full = active_parent_full.get(int(req.parent_id_2))
        if p1_full and p2_full:
            mdb = str(master_data.configured_master_mdb_path(base_dir))
            aff = affinity_calc.calculate_affinity(mdb, req.card_id, p1_full, p2_full)
            computed_affinity = aff['total']
            succession_rank_point = computed_affinity
            print(f"[start_career] affinity={computed_affinity} (chara={aff['chara_compat']} race={aff['race_compat']})", flush=True)
        else:
            print(f"[start_career] affinity: missing parent data ({req.parent_id_1}={bool(p1_full)} {req.parent_id_2}={bool(p2_full)})", flush=True)
    except Exception as e:
        print(f"[start_career] affinity calc FAILED: {e}", flush=True)

    print(f"[start_career] parents={req.parent_id_1}(rank={p1_rank.get('rank') if p1_rank else '?'}) {req.parent_id_2}(rank={p2_rank.get('rank') if p2_rank else '?'}) sp={succession_rank_point}", flush=True)

    # Only clean up a leftover career if load/index already showed one active.
    # Calling single_mode/load with no career → 102 error → cascades to 217 on
    # the next pre_single_mode/index. Real client: start_session → load/index →
    # pre_single_mode/index (no single_mode/load probe).
    #
    # Retry the load once after a 217/201-flap — leftover detection must run
    # against a freshly-anchored session, otherwise career_light reflects a
    # stale server-side state and finish_career returns 217.
    career_light = data.get('single_mode_chara_light') or None
    if not career_light:
        for _extra in range(1):
            try:
                res2 = active_client.call('load/index', {'adid': ''})
                data = res2.get('data', {})
                active_client.refresh_cached_account_state(data)
                update_start_state(data)
                career_light = data.get('single_mode_chara_light') or None
                if career_light:
                    break
            except Exception:
                break
    leftover_turn = None
    if career_light:
        # Career already visible from load/index — probe for exact turn,
        # then gracefully finish or force-delete.
        try:
            existing = active_client.load_career(scenario_id=req.scenario_id)
            chara = (existing.get('data') or {}).get('chara_info') or {}
            if chara:
                leftover_turn = int(chara.get('turn') or 0)
        except Exception:
            leftover_turn = None  # server doesn't want to give us the lifespan
        if leftover_turn is not None:
            print(f"[start_career] leftover career detected (turn={leftover_turn}); attempting graceful finish", flush=True)
            try:
                fc = active_client.finish_career(current_turn=leftover_turn, is_force_delete=False)
                print(f"[start_career] finish_career OK rc={(fc or {}).get('data_headers', {}).get('result_code')}", flush=True)
            except Exception as e:
                print(f"[start_career] finish failed ({e}); force-deleting", flush=True)
                try:
                    active_client.finish_career(current_turn=leftover_turn or 99, is_force_delete=True)
                except Exception as e2:
                    print(f"[start_career] force_delete also failed: {e2}; hard-resetting", flush=True)
                    active_client.hard_reset()
        else:
            print(f"[start_career] career_light set but load_career empty; skipping cleanup", flush=True)
    else:
        print(f"[start_career] no active career; skipping cleanup", flush=True)
    try:
        active_client.pre_single_mode()
        dna_sleep(0.5, 1.5)
    except Exception as e:
        print(f"[start_career] pre_single_mode FAILED: {e}", flush=True)

    start_payload = dict(
        card_id=req.card_id,
        support_card_ids=req.support_card_ids,
        friend_viewer_id=req.friend_viewer_id,
        friend_card_id=req.friend_card_id,
        parent_id_1=req.parent_id_1,
        parent_id_2=req.parent_id_2,
        rental_viewer_id=req.rental_viewer_id,
        rental_trained_chara_id=req.rental_trained_chara_id,
        scenario_id=req.scenario_id,
        deck_id=req.deck_id,
        use_tp=req.use_tp,
        tp_info={'current_tp': tp_info.get('current_tp'), 'max_tp': tp_info.get('max_tp'), 'max_recovery_time': tp_info.get('max_recovery_time', 0)},
        current_money=current_money,
        succession_rank_point=succession_rank_point,
        difficulty_id=req.difficulty_id,
        difficulty=req.difficulty,
        is_boost=req.is_boost,
        boost_story_event_id=req.boost_story_event_id
    )
    print(f"[start_career] payload: {json.dumps(start_payload, ensure_ascii=False)}", flush=True)
    result = active_client.start_career(
        card_id=req.card_id,
        support_card_ids=req.support_card_ids,
        friend_viewer_id=req.friend_viewer_id,
        friend_card_id=req.friend_card_id,
        parent_id_1=req.parent_id_1,
        parent_id_2=req.parent_id_2,
        rental_viewer_id=req.rental_viewer_id,
        rental_trained_chara_id=req.rental_trained_chara_id,
        scenario_id=req.scenario_id,
        deck_id=req.deck_id,
        use_tp=req.use_tp,
        tp_info=tp_info,
        current_money=current_money,
        succession_rank_point=succession_rank_point,
        difficulty_id=req.difficulty_id,
        difficulty=req.difficulty,
        is_boost=req.is_boost,
        boost_story_event_id=req.boost_story_event_id
    )
    try:
        active_client.change_support_card_deck_party(active_support_card_deck_array)
        print(f"[start_career] support_card_deck/change_party OK", flush=True)
    except Exception as e:
        print(f"[start_career] support_card_deck/change_party FAILED: {e}", flush=True)
    return {"success": True, "result": result}

def apply_career_result(result):
    global active_account, active_dashboard_data
    result_data = result.get('data', {})
    update_start_state(result_data)
    account = get_account_status(result_data, result)
    chara_info = result_data.get('chara_info') or {}
    if chara_info:
        account["career"] = account.get("career") or {}
        card_id = str(chara_info.get('card_id', account["career"].get("card_id", '')))
        account["career"].update({
            "active": True,
            "card_id": card_id,
            "name": chara_map.get(card_id, f"Unknown ({card_id})"),
            "turn": chara_info.get('turn', 0),
            "scenario_id": chara_info.get('scenario_id', 0),
            "fans": chara_info.get('fans', 0),
            "vital": chara_info.get('vital', 0),
            "max_vital": chara_info.get('max_vital', 0)
        })
    active_account = account
    if active_dashboard_data:
        active_dashboard_data["account"] = account
    return account, chara_info

def _build_dashboard_from_login_response(res):
    """Populate all dashboard globals from a login/load_index response. Returns dashboard dict."""
    global active_account, active_start_state, active_support_card_deck_array, active_parent_cards, active_parent_rank_points, active_parent_full, active_dashboard_data
    d = res.get('data', {})
    career_data = None
    if d.get('single_mode_chara_light') or d.get('single_mode_chara'):
        try:
            # Extract scenario_id from existing career data
            sm_scenario = 4
            sm_light = d.get('single_mode_chara_light') or {}
            sm_chara = d.get('single_mode_chara') or {}
            if isinstance(sm_light, dict) and sm_light.get('scenario_id'):
                sm_scenario = int(sm_light['scenario_id'])
            elif isinstance(sm_chara, dict) and sm_chara.get('scenario_id'):
                sm_scenario = int(sm_chara['scenario_id'])
            elif d.get('chara_info') and isinstance(d['chara_info'], dict) and d['chara_info'].get('scenario_id'):
                sm_scenario = int(d['chara_info']['scenario_id'])
            career_res = active_client.load_career(scenario_id=sm_scenario)
            career_data = career_res.get('data')
        except Exception:
            pass
    account = get_account_status(d, career_data)
    active_account = account
    active_start_state = {}
    active_support_card_deck_array = []
    active_parent_cards = {}
    active_parent_rank_points = {}
    active_parent_full = {}
    update_start_state(d)
    umas = []
    for card in d.get('card_list', []):
        cid = str(card.get('card_id', card.get('id', '')))
        umas.append({'id': cid, 'name': chara_map.get(cid, f"Unknown ({cid})")})
    supports = []
    support_lb = {}
    for s in d.get('support_card_list', []):
        sid = str(s.get('support_card_id', s.get('id', '')))
        support_lb[sid] = s.get('limit_break_count', 0)
        info = support_map.get(sid)
        if info:
            supports.append({'id': sid, 'limit_break_count': support_lb[sid], 'name': info['name'], 'type': display_support_type(info['type']), 'rarity': info['rarity']})
        else:
            supports.append({'id': sid, 'limit_break_count': support_lb[sid], 'name': f"Unknown ({sid})", 'type': 'Unknown', 'rarity': '?'})
    decks = [
        _dashboard_deck_from_raw(deck, supports)
        for deck in d.get('support_card_deck_array', [])
    ]
    parents = []
    veteran_affinity_mdb = master_data.configured_master_mdb_path(base_dir)
    if not veteran_affinity_mdb or not Path(veteran_affinity_mdb).exists():
        veteran_affinity_mdb = None
    for chara in d.get('trained_chara', []):
        raw_id = str(chara.get('card_id', ''))
        if '{' in raw_id or '-' in raw_id or not raw_id.isdigit():
            found = False
            for key, val in chara.items():
                val_str = str(val)
                if val_str.isdigit() and len(val_str) >= 4:
                    raw_id = val_str
                    found = True
                    break
            if not found:
                continue
        cid = raw_id
        tree = {
            "self": {"card_id": cid, "name": chara_map.get(cid, f"Unknown ({cid})"), "factors": [], "wins": get_win_summary(chara.get('win_saddle_id_array', []))},
            "p1": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([])},
            "p2": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([])},
            "gp1": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([])},
            "gp2": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([])},
            "gp3": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([])},
            "gp4": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([])}
        }
        tree["self"]["factors"] = get_factors(get_chara_factor_ids(chara), cid)
        for sc in chara.get('succession_chara_array', []):
            pos = sc.get('position_id')
            sc_cid = sc.get('card_id', 0)
            key = {10: "p1", 20: "p2", 11: "gp1", 12: "gp2", 21: "gp3", 22: "gp4"}.get(pos, "")
            if key:
                tree[key]["card_id"] = sc_cid
                tree[key]["name"] = chara_map.get(str(sc_cid), f"Unknown ({sc_cid})")
                fid_arr = sc.get('factor_id_array') or [(f.get('factor_id') or 0) for f in (sc.get('factor_info_array') or [])]
                tree[key]["factors"] = get_factors(fid_arr, sc_cid)
                tree[key]["wins"] = get_win_summary(sc.get('win_saddle_id_array', []))
        stats = get_trained_stats(chara)
        skills = get_skill_names(get_trained_skill_ids(chara))
        veteran_affinity = {}
        if veteran_affinity_mdb:
            try:
                veteran_affinity = affinity_calc.calculate_veteran_affinity(
                    str(veteran_affinity_mdb),
                    chara,
                )
            except Exception as exc:
                print(
                    f"[veteran] affinity unavailable for {chara.get('trained_chara_id')}: {exc}",
                    flush=True,
                )
        parents.append({
            'instance_id': chara.get('trained_chara_id'),
            'card_id': cid,
            'name': chara_map.get(cid, f"Unknown ({cid})"),
            'rank': chara.get('rank', 0),
            'rank_score': chara.get('rank_score', 0),
            'acquired_at': chara.get('create_time') or chara.get('created_at') or chara.get('register_time') or chara.get('trained_chara_register_time') or chara.get('complete_time') or chara.get('end_time') or chara.get('updated_at') or 0,
            'stats': stats,
            'aptitudes': get_trained_aptitudes(chara),
            'style_aptitudes': get_trained_style_aptitudes(chara),
            'skills': skills,
            'factors': tree['self']['factors'],
            'wins': tree['self']['wins'],
            'affinity': veteran_affinity,
            'tree': tree,
        })
        lineage_cards = [int(cid)]
        for sc in chara.get('succession_chara_array', []) or []:
            sc_cid = sc.get('card_id', 0)
            if sc_cid:
                lineage_cards.append(int(sc_cid))
        active_parent_cards[int(chara.get('trained_chara_id'))] = lineage_cards
        active_parent_rank_points[int(chara.get('trained_chara_id'))] = {'rank': chara.get('rank', 0), 'rank_score': chara.get('rank_score', 0)}
        active_parent_full[int(chara.get('trained_chara_id'))] = chara
    active_dashboard_data = {"success": True, "account": account, "umas": umas, "supports": supports, "decks": decks, "parents": parents}
    try:
        save_load_index_snapshot(
            runtime_output_root(),
            dashboard=active_dashboard_data,
            load_index_data=d,
        )
    except Exception as exc:
        print(f"[snapshot] unable to persist load/index cache: {exc}", flush=True)
    return active_dashboard_data


@app.post("/api/login")
async def login(req: LoginRequest):
    from uma_api.client import UmaClient, get_ticket
    from career_bot.delay import GateKeeper
    global active_client, active_account, active_dashboard_data, active_start_state, active_support_card_deck_array, active_parent_cards, active_parent_rank_points, pending_game_auth_config, raw_load_index_response, active_selection
    try:
        chara = None
        cfg = dict(pending_game_auth_config)
        pending_game_auth_config = {}

        active_client = None
        active_account = None
        active_dashboard_data = None
        active_start_state = {}
        active_support_card_deck_array = []
        active_parent_cards = {}
        active_parent_rank_points = {}
        raw_load_index_response = None
        active_selection = {
            "deck": None,
            "friend": None,
            "trainee": None,
            "veterans": []
        }

        has_form_creds = bool(req.username and req.password)
        if req.steam_id and req.steam_session_ticket:
            sid = str(req.steam_id)
            tkt = str(req.steam_session_ticket)
            print('Using provided Steam ticket')
        elif has_form_creds:
            sid, tkt = get_ticket(req.username, req.password, req.code)
        else:
            raise Exception('Steam credentials required')

        if not cfg.get('steam_id') or not cfg.get('steam_session_ticket'):
            cfg.update({
                'steam_id': sid,
                'steam_session_ticket': tkt,
            })
        cfg['steam_password_seed'] = req.password
        if req.username:
            cfg['steam_username'] = req.username
        if not has_fresh_auth_config(cfg):
            raise Exception('Fresh in-game auth capture required; switch to the target in-game account, restart capture, then login again')

        c = UmaClient(cfg, trace_enabled=True)
        gated_client = GateKeeper(c)
        res = gated_client.login()
        if not res:
            raise HTTPException(status_code=401, detail="Game login failed")
        active_client = gated_client
        cfg['res_ver'] = c.res_ver
        cfg['app_ver'] = c.app_ver
        if c.viewer_id:
            cfg['viewer_id'] = int(c.viewer_id)
        if c.auth_key_hex and c.auth_key_hex != 'YOUR_AUTH_KEY_HERE':
            cfg['auth_key'] = c.auth_key_hex
        save_auth_cache(cfg)
        dashboard = _build_dashboard_from_login_response(res)
        _refresh_dashboard_friend_supports()
        return active_dashboard_data or dashboard
    except Exception as e:
        msg = str(e)
        if "STEAM_GUARD_REQUIRED" in msg:
             pending_game_auth_config = cfg
             return {"success": False, "needs_2fa": True}
        return {"success": False, "detail": str(e)}

@app.get("/api/session")
async def session_status():
    global active_client, active_dashboard_data, active_account, active_selection
    if not active_client or not active_dashboard_data:
        return {"success": False}
    
    data = dict(active_dashboard_data)
    if active_account:
        data["account"] = active_account
    data["selection"] = active_selection
    data["success"] = True
    return data

class UISelectionRequest(BaseModel):
    selection: dict

@app.post("/api/selection")
async def update_selection(req: UISelectionRequest):
    global active_selection
    active_selection = req.selection
    return {"success": True}

@app.post("/api/support-decks/update")
async def update_support_deck(req: SupportDeckUpdateRequest):
    global active_support_card_deck_array, active_dashboard_data
    if not active_client:
        raise HTTPException(status_code=401, detail="Not logged in")
    if dailies_runner.running:
        raise HTTPException(status_code=409, detail="Cannot edit support decks while dailies are active")
    if career_runner.snapshot().get("running"):
        raise HTTPException(status_code=409, detail="Cannot edit support decks while a career is active")

    cached_deck_ids = {
        int(deck.get('deck_id') or 0)
        for deck in (active_support_card_deck_array or [])
        if 1 <= int(deck.get('deck_id') or 0) <= 10
    }
    if cached_deck_ids != set(range(1, 11)):
        raise HTTPException(status_code=409, detail="Support deck state is incomplete; reload the account before editing")

    owned_supports = list((active_dashboard_data or {}).get('supports') or [])
    owned_ids = {int(item.get('id') or 0) for item in owned_supports if int(item.get('id') or 0)}
    requested_ids = [int(card_id or 0) for card_id in (req.support_card_ids or []) if int(card_id or 0)]
    unavailable = [card_id for card_id in requested_ids if card_id not in owned_ids]
    if unavailable:
        raise HTTPException(status_code=400, detail=f"Support cards are not owned: {unavailable}")

    try:
        updated_party = _replace_support_deck_party(
            active_support_card_deck_array,
            req.deck_id,
            req.name,
            requested_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    active_client.change_support_card_deck_party(updated_party)
    active_support_card_deck_array = updated_party
    dashboard_decks = [
        _dashboard_deck_from_raw(deck, owned_supports)
        for deck in updated_party
    ]
    if active_dashboard_data is None:
        active_dashboard_data = {}
    active_dashboard_data['decks'] = dashboard_decks
    return {
        'success': True,
        'deck_id': int(req.deck_id),
        'decks': dashboard_decks,
    }


@app.post("/api/veteran/remove")
async def remove_veterans(req: VeteranRemoveRequest):
    global active_dashboard_data, active_account, active_selection
    if not active_client:
        raise HTTPException(status_code=401, detail="Not logged in")
    if dailies_runner.running:
        raise HTTPException(status_code=409, detail="Cannot remove veterans while dailies are active")
    ids = [int(v) for v in (req.trained_chara_id_array or []) if int(v)]
    if not ids:
        raise HTTPException(status_code=400, detail="No trained_chara_id_array provided")
    res = active_client.call('trained_chara/remove', {'trained_chara_id_array': ids})
    if not res or not res.get('data'):
        return {'success': False, 'detail': 'Remove request failed', 'response': res}
    load_res = active_client.login()
    data = _build_dashboard_from_login_response(load_res)
    removed = set(ids)
    active_selection['veterans'] = [
        v for v in (active_selection.get('veterans') or [])
        if int(v.get('instance_id') or 0) not in removed
    ]
    data['selection'] = active_selection
    data['removed_ids'] = ids
    return data

@app.get("/veteran", response_class=HTMLResponse)
async def veteran_page():
    return await root()

@app.get("/dailies", response_class=HTMLResponse)
async def dailies_page():
    return await root()

@app.post("/api/capture-login")
def capture_login():
    global active_client, active_account, active_dashboard_data, active_start_state
    global active_parent_cards, active_parent_rank_points, raw_load_index_response
    global active_selection, pending_game_auth_config

    timeout_sec = int(os.environ.get('SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC', '120'))
    deadline = time.time() + timeout_sec

    captured_data = {}
    done = {'ok': False}

    def on_message(message, data):
        if message.get('type') == 'error':
            return
        payload = message.get('payload') or {}
        if payload.get('type') == 'creds' and payload.get('app_ver') and payload.get('res_ver'):
            try:
                from uma_api.client import unpack_request
                wire = unpack_request(payload.get('body') or '', payload.get('udid') or '')
                for key in ('viewer_id', 'device_id', 'device_name', 'graphics_device_name',
                            'ip_address', 'platform_os_version', 'locale',
                            'steam_id', 'steam_session_ticket'):
                    if wire and wire.get(key) is not None:
                        payload[key] = wire.get(key)
            except Exception:
                pass
            captured_data.update(payload)
            done['ok'] = True

    remote = os.environ.get('FRIDA_REMOTE', '')
    device = frida.get_device_manager().add_remote_device(remote) if remote else frida.get_local_device()
    needle = PROCESS_NAME.lower()
    procs = device.enumerate_processes()
    match = [p for p in procs if needle in p.name.lower()]
    if not match:
        return {"success": False, "detail": f"Game not running ({PROCESS_NAME})"}

    session = None
    try:
        session = device.attach(match[0].pid)
        script = session.create_script(JS_CODE)
        script.on('message', on_message)
        script.load()
        print('[capture-login] Attached. Make any in-game action to capture auth...', flush=True)
        while time.time() < deadline:
            if done['ok'] and has_fresh_auth_config(captured_data):
                break
            dna_sleep(0.5, 0.5)
    except Exception as e:
        return {"success": False, "detail": f"Frida error: {e}"}
    finally:
        if session:
            try: session.detach()
            except Exception: pass

    if not done['ok'] or not has_fresh_auth_config(captured_data):
        return {"success": False, "detail": "No auth captured within timeout. Make an in-game action and try again."}

    cfg = dict(captured_data)
    save_auth_cache(cfg)

    try:
        c = UmaClient(cfg, trace_enabled=True)
        gated_client = GateKeeper(c)
        res = gated_client.login()
        if not res:
            return {"success": False, "detail": "Game login failed"}
        active_client = gated_client
        raw_load_index_response = None
        active_selection = {"deck": None, "friend": None, "trainee": None, "veterans": []}
        cfg['res_ver'] = c.res_ver
        cfg['app_ver'] = c.app_ver
        if c.viewer_id:
            cfg['viewer_id'] = int(c.viewer_id)
        if c.auth_key_hex and c.auth_key_hex != 'YOUR_AUTH_KEY_HERE':
            cfg['auth_key'] = c.auth_key_hex
        save_auth_cache(cfg)
        dashboard = _build_dashboard_from_login_response(res)
        print('[capture-login] Login successful.', flush=True)
        return {"success": True, "account": active_account}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.post("/api/logout")
async def logout():
    global active_client, active_account, active_dashboard_data, active_start_state, active_parent_cards, active_parent_rank_points, raw_load_index_response, pending_game_auth_config, active_selection
    dailies_runner.stop()
    active_client = None
    active_account = None
    active_dashboard_data = None
    active_start_state = {}
    active_parent_cards = {}
    active_parent_rank_points = {}
    raw_load_index_response = None
    pending_game_auth_config = {}
    active_selection = {
        "deck": None,
        "friend": None,
        "trainee": None,
        "veterans": []
    }
    return {"success": True}

@app.post("/api/career/start")
async def start_career(req: StartCareerRequest):
    _assert_independent_training_idle()
    if dailies_runner.running:
        return {"success": False, "detail": "Dailies are running — stop them first"}
    try:
        started = start_career_from_request(req)
        if not started.get("success"):
            return started
        account, chara_info = apply_career_result(started["result"])
        return {"success": True, "account": account, "chara_info": chara_info}
    except Exception as e:
        return {"success": False, "detail": str(e)}

backend_loop_thread = None
backend_loop_stop = False
backend_loop_status = {
    "active": False,
    "phase": "idle",
    "message": "",
    "wait_until": 0.0,
}


def _set_backend_loop_status(*, active=None, phase=None, message=None, wait_seconds=None):
    global backend_loop_status
    next_status = dict(backend_loop_status)
    if active is not None:
        next_status["active"] = bool(active)
    if phase is not None:
        next_status["phase"] = str(phase)
    if message is not None:
        next_status["message"] = str(message)
    if wait_seconds is not None:
        wait_seconds = max(0.0, float(wait_seconds or 0.0))
        next_status["wait_until"] = time.time() + wait_seconds if wait_seconds > 0 else 0.0
    backend_loop_status = next_status
    return dict(next_status)


def _career_runner_snapshot():
    snapshot = career_runner.snapshot()
    loop = dict(backend_loop_status)
    wait_until = float(loop.get("wait_until") or 0.0)
    loop["remaining_sec"] = max(0, int(round(wait_until - time.time()))) if wait_until else 0
    snapshot["loop"] = loop
    return snapshot


def _interruptible_sleep(total_sec):
    """Sleep total_sec in 1s slices; return False if backend_loop_stop is set."""
    end = time.monotonic() + total_sec
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return True
        if backend_loop_stop:
            return False
        time.sleep(min(1.0, remaining))


def manage_career_loop(req, preset, initial_result):
    global backend_loop_stop, active_account, active_client
    max_steps = max(1, min(int(req.max_steps or 2500), 3000))
    consecutive_fails = 0
    auth_failures = 0
    _set_backend_loop_status(active=True, phase="starting", message="Starting career loop", wait_seconds=0)

    # Pacing: preset is the source of truth; req may have defaults if the
    # frontend's activeCareer branch skipped these fields.
    loop_run_delay_min = int(preset.get("run_delay_min_min") or req.run_delay_min_min or 10)
    loop_run_delay_max = int(preset.get("run_delay_max_min") or req.run_delay_max_min or 50)
    loop_tp_mode = preset.get("tp_mode") or req.tp_mode or "carat"
    # Force the request to use the preset's tp_mode so acquire_start →
    # start_career_from_request picks it up regardless of what the frontend sent.
    req.tp_mode = loop_tp_mode

    def acquire_start():
        """Start a career, handling TP wait/recover and transient failures.

        Returns the career-start result dict, or None if the loop should stop
        (TP exhausted with stop mode, too many failures, or stop requested).
        """
        nonlocal consecutive_fails, auth_failures
        while not backend_loop_stop:
            try:
                _set_backend_loop_status(active=True, phase="starting", message="Starting next career", wait_seconds=0)
                started = start_career_from_request(req)
                if not started.get("success"):
                    detail = started.get("detail")
                    if detail == "TP_EXHAUSTED":
                        print(f'[loop] TP exhausted ({started.get("current_tp")} < {req.use_tp}), stopping.', flush=True)
                        return None
                    if detail == "TP_REGEN_WAIT":
                        current_tp = int(started.get("current_tp") or 0)
                        wait_sec = compute_regen_wait_seconds(req.use_tp, current_tp)
                        _set_backend_loop_status(
                            active=True,
                            phase="waiting_tp",
                            message=f"Waiting for TP regen ({current_tp}/{req.use_tp})",
                            wait_seconds=wait_sec,
                        )
                        print(f'[loop] waiting {wait_sec/60:.0f}m for TP regen ({current_tp} < {req.use_tp})', flush=True)
                        if not _interruptible_sleep(wait_sec):
                            return None
                        # Session may have expired during long wait; re-init before
                        # the next load/index call on the retry.
                        try:
                            active_client.call('tool/start_session', {'attestation_type': 0, 'device_token': None})
                            print(f'[loop] start_session after TP regen wait OK', flush=True)
                        except Exception:
                            # Session ticket expired during long wait — full re-auth
                            print(f'[loop] start_session failed after TP wait, re-authing...', flush=True)
                            try:
                                if auto_login_from_cache():
                                    print(f'[loop] re-auth after TP wait OK', flush=True)
                                else:
                                    print(f'[loop] re-auth after TP wait failed', flush=True)
                            except Exception as ae:
                                print(f'[loop] re-auth after TP wait error: {ae}', flush=True)
                        continue
                    consecutive_fails += 1
                    if consecutive_fails >= 5:
                        return None
                    for _ in range(15):
                        if backend_loop_stop:
                            return None
                        dna_sleep(1.0, 1.0)
                    continue
                consecutive_fails = 0
                return started["result"]
            except Exception as e:
                err_str = str(e)
                # 201 = session expired; re-auth via headless Steam login
                if "201" in err_str:
                    auth_failures += 1
                    print(f'[loop] session expired (201) on start attempt {auth_failures}/3, re-authing...', flush=True)
                    if auth_failures >= 3:
                        print(f'[loop] 3 failed auth attempts, stopping.', flush=True)
                        return None
                    if auto_login_from_cache():
                        print(f'[loop] re-auth OK, retrying career start', flush=True)
                        consecutive_fails = 0
                        continue
                    print(f'[loop] re-auth failed', flush=True)
                    # fall through to normal retry delay
                consecutive_fails += 1
                if consecutive_fails >= 5:
                    return None
                for _ in range(15):
                    if backend_loop_stop:
                        return None
                    dna_sleep(1.0, 1.0)
        return None

    current_result = initial_result

    while not backend_loop_stop:
        # Acquire a career to run if we don't already have a started one. This is
        # the path when launched at low TP (initial_result is None): the loop waits
        # for regen / recovers carats here before career 1.
        if current_result is None:
            current_result = acquire_start()
            if current_result is None:
                return
            account, chara_info = apply_career_result(current_result)
            active_account = account

        _set_backend_loop_status(active=True, phase="running", message="Career in progress", wait_seconds=0)
        career_runner.start(active_client, preset, current_result, max_steps, burn_clocks=req.burn_clocks, dev_mode=req.dev_mode)

        while career_runner.snapshot().get("running"):
            if backend_loop_stop:
                career_runner.stop()
                return
            dna_sleep(1.0, 1.0)

        status = career_runner.snapshot()
        if status.get("last_error"):
            err_str = str(status["last_error"])
            # 201 = session expired; re-auth instead of blind fail increment
            if "201" in err_str:
                auth_failures += 1
                print(f'[loop] session expired (201) during career ({auth_failures}/3), re-authing...', flush=True)
                if auth_failures >= 3:
                    print(f'[loop] 3 failed auth attempts, stopping.', flush=True)
                    break
                if auto_login_from_cache():
                    print(f'[loop] re-auth OK, continuing loop', flush=True)
                    consecutive_fails = 0
                else:
                    print(f'[loop] re-auth failed', flush=True)
                    consecutive_fails += 1
                    if consecutive_fails >= 3:
                        break
            else:
                consecutive_fails += 1
                if consecutive_fails >= 3:
                    break
        else:
            consecutive_fails = 0
        # Always clear the local active-career flag before the next start attempt.
        # start_career_from_request refuses if it thinks a career is active; the
        # leftover (errored/stuck) run is cleaned up there via graceful-finish/force-delete.
        if active_account and "career" in active_account and active_account["career"]:
            active_account["career"]["active"] = False

        if not req.dev_mode:
            break

        delay_sec = pick_delay_seconds(loop_run_delay_min, loop_run_delay_max)
        _set_backend_loop_status(
            active=True,
            phase="waiting_delay",
            message="Waiting before next career",
            wait_seconds=delay_sec,
        )
        print(f'[loop] waiting {delay_sec/60:.1f}m before next career', flush=True)
        if not _interruptible_sleep(delay_sec):
            return

        # Force re-acquire of the next career at the top of the loop.
        current_result = None


def _manage_career_loop_thread(req, preset, initial_result):
    try:
        manage_career_loop(req, preset, initial_result)
    finally:
        _set_backend_loop_status(active=False, phase="idle", message="", wait_seconds=0)


@app.post("/api/career/run")
async def run_career(req: RunCareerRequest):
    global active_account, backend_loop_thread
    _assert_independent_training_idle()
    with global_lock:
        if dailies_runner.running:
            return {"success": False, "detail": "Dailies are running — stop them first"}
        if career_runner.snapshot().get("running") or (backend_loop_thread and backend_loop_thread.is_alive()):
            return {"success": False, "detail": "Career runner loop already active"}
        preset_name = req.preset_name or "xguri parent"
        preset = preset_store.read_one(preset_name)
        if not preset:
            return {"success": False, "detail": f"{preset_name} preset missing"}
        preset = apply_runtime_preset_overrides(preset, req.preset_overrides)

    # Apply preset-level turn delay to the global delay module
    _apply_preset_turn_delay(preset)
    
    try:
        with global_lock:
            account = active_account or {}
            career = account.get("career") or {}
            if career.get("active"):
                index_result = active_client.call('load/index')
                load_data = index_result.get('data', {})
                update_start_state(load_data)

                account = get_account_status(load_data)
                active_account = account
                career = account.get("career") or {}

        if career.get("active"):
            load_scenario = int(career.get("scenario_id") or preset.get("scenario_id", 4))
            career_result = active_client.load_career(scenario_id=load_scenario)
            career_data = career_result.get('data', {})
            
            account = get_account_status(load_data, career_result)
            active_account = account
            
            career_status = account.get("career")
            req.card_id = int(career_status.get("card_id") or 0)
            req.support_card_ids = career_status.get("support_card_ids")
            req.friend_viewer_id = int(career_status.get("friend_viewer_id") or 0)
            req.friend_card_id = int(career_status.get("friend_card_id") or 0)
            req.parent_id_1 = int(career_status.get("parent_id_1") or 0)
            req.parent_id_2 = int(career_status.get("parent_id_2") or 0)
            req.rental_viewer_id = int(career_status.get("rental_viewer_id") or 0)
            req.rental_trained_chara_id = int(career_status.get("rental_trained_chara_id") or 0)
            req.deck_id = int(career_status.get("deck_id") or 0)
            req.scenario_id = int(career_status.get("scenario_id") or preset.get("scenario_id", 4))
            
            chara_info = career_data.get('chara_info') or {}
            if active_dashboard_data:
                active_dashboard_data["account"] = account
            result = career_result
        else:
            if not req.scenario_id:
                req.scenario_id = int(preset.get("scenario_id", 4))
            started = start_career_from_request(req)
            if not started.get("success"):
                # In dev_mode, a TP regen wait must not abort the launch. Start the loop
                # with no seed career and let it wait for TP, then start career 1.
                if req.dev_mode and started.get("detail") == "TP_REGEN_WAIT":
                    result = None
                    chara_info = {}
                else:
                    return started
            else:
                result = started["result"]
                account, chara_info = apply_career_result(result)

        apply_deck_type_counts(preset, req=req, chara_info=chara_info)
        
        if req.dev_mode:
            backend_loop_stop = False
            _set_backend_loop_status(active=True, phase="starting", message="Starting career loop", wait_seconds=0)
            backend_loop_thread = threading.Thread(target=_manage_career_loop_thread, args=(req, preset, result), daemon=True)
            backend_loop_thread.start()
            dna_sleep(0.5, 0.5)
        else:
            _set_backend_loop_status(active=False, phase="idle", message="", wait_seconds=0)
            career_runner.start(active_client, preset, result, max(1, min(int(req.max_steps or 2500), 3000)), burn_clocks=req.burn_clocks, dev_mode=req.dev_mode)
            
        return {"success": True, "account": account, "chara_info": chara_info, "runner": _career_runner_snapshot()}
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.get("/api/career/runner")
async def career_runner_status():
    return {"success": True, "runner": _career_runner_snapshot()}


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _legend_race_options(response):
    rows = []
    for node in _walk_dicts(response):
        value = node.get("daily_legend_race_record_array")
        if isinstance(value, list):
            rows = value
            break

    options = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        boss_data = row.get("boss_data") if isinstance(row.get("boss_data"), dict) else {}
        race_id = int(
            row.get("daily_legend_race_id")
            or row.get("legend_race_id")
            or row.get("id")
            or boss_data.get("daily_legend_race_id")
            or 0
        )
        if not race_id or race_id in seen:
            continue
        seen.add(race_id)
        card_id = int(
            boss_data.get("card_id")
            or boss_data.get("chara_id")
            or row.get("card_id")
            or row.get("chara_id")
            or 0
        )
        boss_name = (
            boss_data.get("name")
            or boss_data.get("chara_name")
            or row.get("boss_name")
            or row.get("name")
            or chara_map.get(str(card_id))
            or chara_map.get(card_id)
            or f"Boss #{race_id}"
        )
        options.append({
            "id": race_id,
            "boss": str(boss_name),
            "is_played": bool(
                row.get("is_played")
                or row.get("is_played_today")
                or row.get("play_count")
            ),
            "is_cleared": bool(
                row.get("is_cleared")
                or row.get("clear_flag")
                or row.get("clear_count")
            ),
        })
    return options


@app.get("/api/dailies/status")
async def dailies_status():
    status = dailies_runner.snapshot()
    return {"success": True, "running": bool(status.get("running")), "status": status}


@app.post("/api/dailies/legend_options")
async def dailies_legend_options():
    if not active_client:
        return {"success": False, "detail": "Not logged in", "legend_races": []}
    if dailies_runner.running or career_runner.snapshot().get("running"):
        return {"success": False, "detail": "Bot is busy", "legend_races": []}
    try:
        result = active_client.daily_legend_race_index()
        options = _legend_race_options(result)
        return {
            "success": True,
            "legend_races": options,
            "detail": "" if options else "None available today",
        }
    except Exception as exc:
        return {"success": False, "detail": str(exc), "legend_races": []}


@app.post("/api/dailies/run")
async def dailies_run(req: DailiesRunRequest):
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    tasks = {
        "team_trials": bool(req.team_trials),
        "daily_races": bool(req.daily_races),
        "legend_races": bool(req.legend_races),
        "daily_shop": bool(req.daily_shop),
    }
    if not any(tasks.values()):
        return {"success": False, "detail": "Select at least one daily to run"}
    if (req.daily_races or req.legend_races) and not req.trained_chara_id:
        return {"success": False, "detail": "Pick a veteran to race the daily/legend races"}
    if req.legend_races and not req.legend_race_id:
        return {"success": False, "detail": "Pick which Legend Race to run"}

    with global_lock:
        if dailies_runner.running:
            return {"success": False, "detail": "Dailies are already running"}
        if career_runner.snapshot().get("running") or (
            backend_loop_thread and backend_loop_thread.is_alive()
        ):
            return {"success": False, "detail": "Cannot run dailies while a career is active"}
        career = (active_account or {}).get("career") or {}
        if career.get("active"):
            return {"success": False, "detail": "Cannot run dailies while a career is active"}
        started = dailies_runner.start(
            active_client,
            tasks,
            trained_chara_id=req.trained_chara_id,
            opponent_strength=req.opponent_strength,
            legend_race_id=req.legend_race_id,
        )
    if not started:
        return {"success": False, "detail": "Dailies are already running"}
    return {"success": True, "status": dailies_runner.snapshot()}


@app.post("/api/dailies/stop")
async def dailies_stop():
    dailies_runner.stop()
    return {"success": True, "status": dailies_runner.snapshot()}


@app.post("/api/tp/refill")
async def tp_refill(req: TpRefillRequest):
    global active_client, active_account, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    try:
        result = active_client.recovery_tp(req.count)
        # Refresh account state
        res = active_client.call('load/index', {'adid': ''})
        data = res.get('data', {})
        active_client.refresh_cached_account_state(data)
        update_start_state(data)
        if active_account:
            active_account = get_account_status(data)
        if active_dashboard_data:
            active_dashboard_data["account"] = active_account
        return {"success": True, "tp": result, "account": active_account}
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.post("/api/account/refresh")
async def account_refresh():
    global active_client, active_account, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    try:
        res = refresh_index_state(active_client)
        data = res.get('data', {})
        update_start_state(data)
        dashboard = _build_dashboard_from_login_response(res)
        return {"success": True, "account": active_account, "parents": dashboard.get("parents", [])}
    except Exception as e:
        return {"success": False, "detail": str(e)}

# mtime-keyed cache for career history — avoids re-parsing all JSON on every load
_history_cache: dict = {"data": None, "newest_mtime": 0.0}

def _read_career_meta(path) -> dict | None:
    """Read only top-level scalar metadata from a career log, skipping the
    massive ``turns`` array (~99% of file size) by truncating at the ``"turns"``
    key and parsing just the prefix as valid JSON (head), then extracting
    ``final_fans`` from the last 1KB (tail, after turns).  ~50× faster than full parse."""
    needed = {'started_at', 'ended_at', 'preset_name', 'status', 'final_turn'}
    try:
        raw = Path(path).read_bytes()
        head = raw[:4096]
        idx = head.find(b'"turns"')
        if idx < 0:
            return None
        # Parse scalars from before the turns array
        truncated = head[:idx].rstrip(b', \n\r\t') + b'}'
        parsed = json.loads(truncated)
        result = {k: parsed[k] for k in needed if k in parsed}

        # final_fans lives after turns — scan the file tail
        result['final_fans'] = 0
        tail = raw[-1024:]
        m = re.search(rb'"final_fans"\s*:\s*(\d+)', tail)
        if m:
            result['final_fans'] = int(m.group(1))

        return result
    except Exception:
        return None

@app.get("/api/career/history")
async def career_run_history():
    from datetime import datetime as _dt
    logs_dir = runtime_output_root() / 'bot_logs'
    if not logs_dir.exists():
        return {"success": True, "runs": []}

    # Find newest mtime across all log files (cheap stat, no read/parse)
    newest_mtime = 0.0
    try:
        for f in logs_dir.iterdir():
            if f.name.startswith("career_log_") and f.suffix == ".json" and f.is_file():
                mtime = f.stat().st_mtime
                if mtime > newest_mtime:
                    newest_mtime = mtime
    except Exception:
        pass

    if _history_cache["data"] is not None and newest_mtime <= _history_cache["newest_mtime"]:
        return _history_cache["data"]

    runs = []
    for f in sorted(logs_dir.glob('career_log_*.json'), reverse=True)[:50]:
        data = _read_career_meta(f)
        if data is None:
            continue
        started = data.get('started_at')
        ended = data.get('ended_at')
        duration_sec = None
        if started and ended:
            duration_sec = int((_dt.fromisoformat(ended) - _dt.fromisoformat(started)).total_seconds())
        runs.append({
            'started_at': started,
            'duration_sec': duration_sec,
            'status': data.get('status'),
            'preset_name': data.get('preset_name', ''),
            'final_turn': data.get('final_turn', 0),
            'final_fans': data.get('final_fans', 0),
        })

    result = {"success": True, "runs": runs}
    _history_cache["data"] = result
    _history_cache["newest_mtime"] = newest_mtime
    return result

@app.post("/api/career/runner/stop")
async def stop_career_runner():
    global backend_loop_stop
    with global_lock:
        backend_loop_stop = True
        loop_active = bool(backend_loop_status.get("active"))
        if loop_active:
            _set_backend_loop_status(active=True, phase="stopping", message="Stopping career loop", wait_seconds=0)
    career_runner.stop()
    return {"success": True, "runner": _career_runner_snapshot()}

class BurnClocksRequest(BaseModel):
    burn_clocks: bool

@app.post("/api/career/runner/burn_clocks")
async def set_burn_clocks(req: BurnClocksRequest):
    career_runner.set_burn_clocks(req.burn_clocks)
    return {"success": True, "runner": career_runner.snapshot()}

@app.post("/api/career/friends")
async def get_friend_list(req: FriendListRequest):
    global active_client, active_dashboard_data, active_account
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    if active_account and active_account.get("career") and active_account["career"].get("active"):
        return {
            "success": True,
            "friends": [],
            "exclude_viewer_ids": [],
            "source": "Active Career (Skip)"
        }

    if (
        not req.exclude_viewer_ids
        and not req.force_refresh
        and active_dashboard_data is not None
        and "friends" in active_dashboard_data
    ):
        return {
            "success": True,
            "friends": active_dashboard_data["friends"],
            "exclude_viewer_ids": active_dashboard_data.get("friendExcludeIds", []),
            "source": "cache",
            "veterans": active_dashboard_data.get("friendVeterans", []),
            "veterans_source": active_dashboard_data.get("friendVeteransSource", "cache"),
        }

    try:
        result = active_client.pre_single_mode(req.exclude_viewer_ids)
        data = result.get('data', {})
        update_start_state(data)
        friends, exclude_viewer_ids, source = normalize_friend_cards(data)
        veterans, veterans_source = normalize_friend_veterans(data)

        if active_dashboard_data is not None:
            active_dashboard_data["friends"] = friends
            active_dashboard_data["friendExcludeIds"] = exclude_viewer_ids
            active_dashboard_data["friendsLoaded"] = True
            active_dashboard_data["friendVeterans"] = veterans
            active_dashboard_data["friendVeteransSource"] = veterans_source
            active_dashboard_data["lastPreSingleModeRaw"] = data

        return {
            "success": True,
            "friends": friends,
            "exclude_viewer_ids": exclude_viewer_ids,
            "source": source,
            "veterans": veterans,
            "veterans_source": veterans_source,
        }
    except Exception as e:
        if active_dashboard_data is not None and active_dashboard_data.get("friends"):
            return {
                "success": True,
                "friends": active_dashboard_data.get("friends", []),
                "exclude_viewer_ids": active_dashboard_data.get("friendExcludeIds", []),
                "source": "cache-after-refresh-error",
                "warning": str(e),
                "veterans": active_dashboard_data.get("friendVeterans", []),
                "veterans_source": active_dashboard_data.get("friendVeteransSource", "cache"),
            }
        return {"success": False, "detail": str(e)}


@app.get("/api/friends/raw")
async def get_friends_raw():
    if not active_dashboard_data:
        return {"success": False, "detail": "No active session yet"}
    raw = active_dashboard_data.get("lastPreSingleModeRaw")
    if raw is None:
        return {"success": False, "detail": "Call /api/career/friends first to populate this cache."}

    def shape(value, depth=0, max_depth=3):
        if depth > max_depth:
            return type(value).__name__
        if isinstance(value, dict):
            return {k: shape(v, depth + 1, max_depth) for k, v in value.items()}
        if isinstance(value, list):
            sample = value[0] if value else None
            return {"<list len=>": len(value), "<item shape>": shape(sample, depth + 1, max_depth)}
        return type(value).__name__

    return {
        "success": True,
        "top_level_keys": sorted(list(raw.keys())),
        "shape": shape(raw, max_depth=2),
        "veterans": len(active_dashboard_data.get("friendVeterans", [])),
        "veterans_source": active_dashboard_data.get("friendVeteransSource", "unknown"),
    }


@app.get("/api/friends/veterans")
async def get_friend_veterans():
    if not active_dashboard_data:
        return {"success": False, "detail": "No active session yet"}
    veterans = active_dashboard_data.get("friendVeterans") or []
    return {
        "success": True,
        "veterans": veterans,
        "source": active_dashboard_data.get("friendVeteransSource", "unknown"),
    }


@app.get("/api/friends/manage")
async def get_friend_management():
    if not active_dashboard_data:
        return {"success": False, "detail": "No active session yet"}
    friends = active_dashboard_data.get("friends") or []
    counts = {}
    for friend in friends:
        key = str(friend.get("friend_state", 0))
        counts[key] = counts.get(key, 0) + 1
    return {
        "success": True,
        "friends": friends,
        "counts": counts,
        "source": active_dashboard_data.get("friendsLoaded") and "cache" or "session",
    }


@app.post("/api/friends/follow")
async def follow_friend(req: FriendManageRequest):
    global active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    try:
        result = active_client.follow_user(req.viewer_id)
        if active_dashboard_data:
            for friend in active_dashboard_data.get("friends", []) or []:
                if int(friend.get("viewer_id") or 0) == int(req.viewer_id):
                    friend["friend_state"] = max(1, int(friend.get("friend_state") or 0))
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.post("/api/friends/unfollow")
async def unfollow_friend(req: FriendManageRequest):
    global active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    try:
        result = active_client.unfollow_user(req.viewer_id)
        if active_dashboard_data:
            for friend in active_dashboard_data.get("friends", []) or []:
                if int(friend.get("viewer_id") or 0) == int(req.viewer_id):
                    friend["friend_state"] = 0
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.post("/api/advisor/recommendations")
async def advisor_recommendations(req: AdvisorRequest):
    if not active_dashboard_data:
        return {"success": False, "detail": "No active session yet"}
    trainee_card_id = int(req.trainee_card_id or 0)
    running_style = int(req.running_style or 0)
    if not trainee_card_id:
        selection = active_selection or {}
        trainee = selection.get("trainee") or {}
        trainee_card_id = int(trainee.get("id") or trainee.get("card_id") or 0)
    if not running_style:
        try:
            running_style = int((preset_store.read_one(active_selection.get("preset") or "") or {}).get("running_style") or 0)
        except Exception:
            running_style = 0
    candidates = advisor.recommend_parent_pool(
        active_dashboard_data.get("parents") or [],
        active_dashboard_data.get("friendVeterans") or [],
        trainee_card_id=trainee_card_id,
        running_style=running_style,
    )
    return {
        "success": True,
        "trainee_card_id": trainee_card_id,
        "running_style": running_style,
        "recommendations": candidates[:24],
    }


@app.post("/api/advisor/aptitude-preview")
async def aptitude_preview(req: dict = None):
    """Predict aptitude grades from selected parent combination + trainee base."""
    try:
        body = req or {}
        parents = body.get("parents") or []
        trainee_card_id = body.get("trainee_card_id")
        prediction = aptitude.predict_aptitude(
            parents, factor_map=factor_map, trainee_card_id=trainee_card_id
        )
        return {
            "success": True,
            **prediction,
        }
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.post("/api/career/action")
async def career_action(req: CareerActionRequest):
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    
    try:
        result = active_client.exec_command(
            command_type=req.command_type,
            command_id=req.command_id,
            current_turn=req.current_turn,
            current_vital=req.current_vital,
            command_group_id=req.command_group_id,
            select_id=req.select_id
        )
        
        data = result.get('data', {})
        return {
            "success": True,
            "chara_info": data.get('chara_info', {}),
            "command_result": data.get('command_result', {})
        }
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.post("/api/career/delete")
async def delete_career(req: DeleteCareerRequest):
    global active_client, active_account, active_dashboard_data, backend_loop_thread
    with global_lock:
        if not active_client:
            return {"success": False, "detail": "Not logged in"}
        if dailies_runner.running:
            return {"success": False, "detail": "Cannot delete career while dailies are active"}
        if career_runner.snapshot().get("running") or (backend_loop_thread and backend_loop_thread.is_alive()):
            return {"success": False, "detail": "Cannot delete career while runner is active"}

        try:
            account = active_account or {}
            career = account.get("career") or {}
            if not career.get("active"):
                load_result = active_client.call('load/index')
                load_data = load_result.get('data', {})
                update_start_state(load_data)
                account = get_account_status(load_data)
                active_account = account
                career = account.get("career") or {}
            current_turn = req.current_turn or career.get("turn", 0) or 1
            if not career.get("active") and not req.current_turn:
                return {"success": False, "detail": "No active career"}
            active_client.finish_career(current_turn=current_turn, is_force_delete=True)
            account["career"] = None
            active_account = account
            if active_dashboard_data:
                active_dashboard_data["account"] = account
            return {"success": True, "account": account}
        except Exception as e:
            return {"success": False, "detail": str(e)}

@app.get("/api/debug/start_state")
async def get_start_state():
    return active_start_state

@app.get("/api/debug/raw_load")
async def get_raw_load():
    return {"error": "raw load/index response storage disabled"}

@app.get("/api/images/{image_name}")
async def get_image(image_name: str):
    name_no_ext = image_name.split('?')[0].replace('.png', '')
    
    exact_path = images_dir / f"{name_no_ext}.png"
    if exact_path.exists():
        return FileResponse(exact_path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    
    for fallback_id in ['100101', '10010', '10000', '10001']:
        fb_path = images_dir / f"{fallback_id}.png"
        if fb_path.exists():
            return FileResponse(fb_path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    
    raise HTTPException(status_code=404, detail="Image not found")


@app.get("/styles.css")
async def styles_css():
    path = base_dir / "public" / "styles.css"
    if path.exists():
        return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="styles.css not found")

@app.get("/app.js")
async def app_js():
    path = base_dir / "public" / "app.js"
    if path.exists():
        return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="app.js not found")


@app.get("/sweep.png")
async def sweep_png():
    path = base_dir / "public" / "sweep.png"
    if path.exists():
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="sweep.png not found")

@app.get("/broom.png")
async def broom_png():
    path = base_dir / "public" / "broom.png"
    if path.exists():
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="broom.png not found")

@app.get("/assets/data/{file_name}")
async def get_asset_data(file_name: str):
    path = base_dir / 'public' / 'assets' / 'data' / file_name
    if path.exists():
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/races/{file_name}")
async def get_race_image(file_name: str):
    path = base_dir / "public" / "races" / file_name
    if path.exists():
        return FileResponse(path, headers={"Cache-Control": "max-age=31536000"})
    raise HTTPException(status_code=404, detail="Race image not found")

@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = base_dir / "public" / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return "index.html not found"

@app.get("/campaigns", response_class=HTMLResponse)
async def campaigns_page():
    return FileResponse(
        base_dir / "public" / "campaigns.html",
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )

@app.get("/campaigns.js")
async def campaigns_js():
    return FileResponse(
        base_dir / "public" / "campaigns.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )

@app.get("/campaigns.css")
async def campaigns_css():
    return FileResponse(
        base_dir / "public" / "campaigns.css",
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/independent-training", response_class=HTMLResponse)
async def independent_training_page():
    return FileResponse(
        base_dir / "public" / "independent-training.html",
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/independent-training.js")
async def independent_training_js():
    return FileResponse(
        base_dir / "public" / "independent-training.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/independent-training.css")
async def independent_training_css():
    return FileResponse(
        base_dir / "public" / "independent-training.css",
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


def set_console_topmost():
    if os.name != 'nt':
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return
        ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
    except Exception:
        pass

def kill_process_by_name(name):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/IM', name, '/F'], capture_output=True, text=True, timeout=10)
        else:
            needle = name.lower()
            procs = frida.get_local_device().enumerate_processes()
            for p in procs:
                if needle in p.name.lower():
                    subprocess.run(['kill', str(p.pid)], capture_output=True, timeout=5)
    except Exception:
        pass

def kill_listeners_on_port(port):
    if os.name != 'nt':
        # Linux: use ss to find PIDs listening on the port
        try:
            proc = subprocess.run(
                ['ss', '-tlnp'],
                capture_output=True, text=True, timeout=5
            )
        except Exception:
            return

        current_pid = os.getpid()
        pids = set()
        marker = f':{port}'
        for line in proc.stdout.splitlines():
            if marker not in line:
                continue
            # ss output: LISTEN 0 128 127.0.0.1:1616 0.0.0.0:* users:(("python",pid=12345,fd=3))
            import re
            for m in re.finditer(r'pid=(\d+)', line):
                pid = int(m.group(1))
                if pid and pid != current_pid:
                    pids.add(pid)

        if not pids:
            return
        print(f"Port {port} already in use; killing listener PID(s): {', '.join(map(str, sorted(pids)))}", flush=True)
        for pid in sorted(pids):
            try:
                subprocess.run(['kill', str(pid)], capture_output=True, timeout=5)
            except Exception:
                pass
        dna_sleep(0.5, 0.5)
        return
    try:
        proc = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True,
            text=True,
            timeout=5
        )
    except Exception:
        return

    current_pid = os.getpid()
    pids = set()
    marker = f':{port}'
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[3].upper() if len(parts) >= 5 else ''
        pid_text = parts[-1]
        if marker not in local_addr or state != 'LISTENING':
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid and pid != current_pid:
            pids.add(pid)

    if not pids:
        return
    print(f"Port {port} already in use; killing listener PID(s): {', '.join(map(str, sorted(pids)))}", flush=True)
    for pid in sorted(pids):
        try:
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, text=True, timeout=5)
        except Exception:
            pass
    dna_sleep(0.5, 0.5)

def has_fresh_auth_config(cfg):
    app_ver = str(cfg.get('app_ver') or '').strip()
    res_ver = str(cfg.get('res_ver') or '').strip()
    if not app_ver or not res_ver:
        return False
    if int(cfg.get('auth_key_len') or 0) != 48:
        return False
    viewer_id = cfg.get('viewer_id')
    udid = str(cfg.get('udid') or '').strip()
    auth_key = str(cfg.get('auth_key') or '').strip().lower()
    if not viewer_id or not udid or not auth_key:
        return False
    if not re.fullmatch(r'[0-9a-f]+', auth_key):
        return False
    if len(auth_key) < 32 or len(auth_key) % 2:
        return False
    if len(udid) != 36 or udid.count('-') != 4:
        return False
    return True

def launch_game():
    try:
        if os.name == 'nt':
            os.startfile(f'steam://rungameid/{APP_ID}')
        else:
            subprocess.Popen(['xdg-open', f'steam://rungameid/{APP_ID}'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f'Failed to launch Umamusume through Steam: {e}')
        return False

def refresh_auth_before_serving(timeout_sec=None):
    global pending_game_auth_config

    cached = load_auth_cache()
    if cached:
        pending_game_auth_config = cached
        print('[auth cache] Loaded saved credentials — skipping game launch.', flush=True)
        return True

    timeout_sec = timeout_sec or int(os.environ.get('SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC', '180'))
    started_at = time.time()
    deadline = started_at + timeout_sec

    print('[NEED TO CAPTURE AUTH]', flush=True)
    if not launch_game():
        return False
    
    print(f'Waiting up to {timeout_sec}s for user to enter game menu', flush=True)

    session = None
    captured_data = {}
    done = {'ok': False}

    def on_message(message, data):
        if message.get('type') == 'error':
            print(f"Frida Error: {message.get('description')}", flush=True)
            return
        payload = message.get('payload') or {}
        if payload.get('type') == 'creds':
            if payload.get('app_ver') and payload.get('res_ver'):
                try:
                    from uma_api.client import unpack
                    wire = unpack(payload.get('body') or '', payload.get('udid') or '')
                    for key in (
                        'viewer_id',
                        'device_id',
                        'device_name',
                        'graphics_device_name',
                        'ip_address',
                        'platform_os_version',
                        'locale',
                        'steam_id',
                        'steam_session_ticket',
                    ):
                        if wire.get(key) is not None:
                            payload[key] = wire.get(key)
                except Exception:
                    pass
                captured_data.update(payload)
                done['ok'] = True

    def _get_device():
        remote = os.environ.get('FRIDA_REMOTE', '')
        if remote:
            return frida.get_device_manager().add_remote_device(remote)
        return frida.get_local_device()

    def _find_and_attach():
        device = _get_device()
        needle = PROCESS_NAME.lower()
        procs = device.enumerate_processes()
        for p in procs:
            if needle in p.name.lower():
                return device.attach(p.pid)
        return device.attach(PROCESS_NAME)

    while time.time() < deadline:
        try:
            session = _find_and_attach()
            break
        except Exception:
            dna_sleep(1.0, 1.0)

    if not session:
        print(f'Error: {PROCESS_NAME} not found within timeout.', flush=True)
        return False

    try:
        script = session.create_script(JS_CODE)
        script.on('message', on_message)
        script.load()

        while time.time() < deadline:
            if done['ok']:
                if has_fresh_auth_config(captured_data):
                    pending_game_auth_config = dict(captured_data)
                    save_auth_cache(captured_data)
                    dna_sleep(2.0, 4.0)
                    kill_process_by_name(PROCESS_NAME)
                    return True
            dna_sleep(0.5, 0.5)
    except Exception as e:
        print(f'Frida injection failed: {e}', flush=True)
    finally:
        if session:
            try:
                session.detach()
            except Exception:
                pass

    print('Auth refresh failed: no fresh credentials captured before timeout.', flush=True)
    return False


def refresh_index_state(client, max_retries=3):
    attempt = 0
    while True:
        try:
            client.regen_sid()
            client.call('tool/start_session', {'attestation_type': 0, 'device_token': None})
            res = client.call('load/index', {'adid': ''})
            client.refresh_cached_account_state(res.get('data') or {})
            return res
        except Exception as exc:
            err = str(exc)
            if '202' in err and attempt < max_retries:
                attempt += 1
                continue
            # 390/394 mean the steam_session_ticket expired, not that the server
            # is busy: start_session keeps returning result_code 1 while every
            # account-scoped endpoint bounces, so retrying this exact sequence
            # loops forever. UmaClient.call regenerates the ticket and retries
            # on its own (STEAM_TICKET_STALE_CODES); if it still fails the
            # session is genuinely unrecoverable, so surface it.
            raise


def auto_login_from_cache():
    global active_client, active_account, active_dashboard_data, active_start_state
    global active_parent_cards, active_parent_rank_points, raw_load_index_response, active_selection
    cfg = load_auth_cache()
    if not cfg:
        return False
    username = cfg.get('steam_username', '')
    password = cfg.get('steam_password_seed', '')
    if not username:
        return False
    from uma_api.client import get_ticket, _steam_keyfile_path
    if not _steam_keyfile_path(username).exists():
        print('[auto-login] No saved refresh token — log in manually via the web UI to save one.', flush=True)
        return False
    try:
        print(f'[auto-login] Logging in as {username}...', flush=True)
        sid, tkt = get_ticket(username, password)
        cfg.update({'steam_id': sid, 'steam_session_ticket': tkt})
        c = UmaClient(cfg, trace_enabled=True)
        gated_client = GateKeeper(c)
        res = gated_client.login()
        if not res:
            print('[auto-login] Game login failed.', flush=True)
            return False
        active_client = gated_client
        cfg['res_ver'] = c.res_ver
        cfg['app_ver'] = c.app_ver
        if c.viewer_id:
            cfg['viewer_id'] = int(c.viewer_id)
        if c.auth_key_hex and c.auth_key_hex != 'YOUR_AUTH_KEY_HERE':
            cfg['auth_key'] = c.auth_key_hex
        save_auth_cache(cfg)
        _build_dashboard_from_login_response(res)
        _refresh_dashboard_friend_supports()
        raw_load_index_response = None
        active_selection = {"deck": None, "friend": None, "trainee": None, "veterans": []}
        print('[auto-login] Done.', flush=True)
        return True
    except Exception as e:
        if 'STEAM_GUARD_REQUIRED' in str(e):
            print('[auto-login] Steam Guard required — log in manually via the web UI.', flush=True)
        else:
            print(f'[auto-login] Failed: {e}', flush=True)
        return False


if __name__ == "__main__":
    import uvicorn
    import signal

    def _shutdown_handler(signum, frame):
        """Gracefully stop career runner on SIGINT/SIGTERM."""
        print("\nShutting down...", flush=True)
        if career_runner:
            career_runner.stop()
        if dailies_runner:
            dailies_runner.stop()
        if independent_runner:
            independent_runner.stop()
        # uvicorn will handle its own cleanup after this

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    try:
        subprocess.run(["git", "pull"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    set_console_topmost()
    kill_listeners_on_port(PORT)
    if not refresh_auth_before_serving():
        raise SystemExit(1)
    auto_login_from_cache()
    print(f"Access the Web UI at: http://127.0.0.1:{PORT}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")
