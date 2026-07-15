# Parent Campaign Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a top-level `/campaigns` Web UI and durable campaign workflow that recommends a Final Parent and four-Uma affinity loop, executes repeated parent-farming runs, evaluates blue/pink spark constraints, and stops only when required targets are met with final setup affinity `>= 150`.

**Architecture:** Evolve the existing SQLite-backed `career_bot/campaigns/` subsystem instead of creating a parallel implementation. Keep planning, target evaluation, rotation simulation, final-setup validation, legacy resolution, preset generation, persistence, and HTTP/UI adapters in separate units; use existing campaign states plus structured `next_action` and `context_json` for pre-run/post-run review. `main.py` remains a thin Web adapter and the existing career runner remains the only owner of turn-by-turn gameplay.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, SQLite/WAL, pytest, vanilla JavaScript, HTML/CSS.

---

## File Structure

### Create

- `career_bot/campaigns/targets.py` — evaluate required/preferred blue and pink spark targets.
- `career_bot/campaigns/final_setup.py` — rank Final Parent candidates and validate the final two-parent setup against the hard affinity gate.
- `career_bot/campaigns/rotation.py` — deterministic four-Uma virtual lineage rotation simulation.
- `career_bot/campaigns/planner.py` — compose existing scanner/race helpers into Final Parent and four-Uma recommendations.
- `career_bot/campaigns/resolver.py` — resolve `LOCKED`/`FLEXIBLE` concrete veteran slots before each run.
- `career_bot/campaigns/preset_policy.py` — generate campaign base presets and per-step runtime overrides.
- `career_bot/campaigns/service.py` — shared application service used by Web endpoints and reusable by MCP adapters.
- `public/campaigns.html` — dedicated top-level Campaigns page.
- `public/campaigns.js` — Campaigns page state, API calls, creation flow, reviews, and active dashboard.
- `public/campaigns.css` — page-specific layout while reusing global theme variables.
- `tests/test_campaign_targets.py`
- `tests/test_campaign_final_setup.py`
- `tests/test_campaign_rotation.py`
- `tests/test_campaign_planner.py`
- `tests/test_campaign_resolver.py`
- `tests/test_campaign_preset_policy.py`
- `tests/test_campaign_service.py`
- `tests/test_campaign_web_api.py`

### Modify

- `career_bot/campaigns/models.py` — add Web campaign specification models while keeping old MCP specs loadable.
- `career_bot/campaigns/store.py` — add active-campaign guard, context helpers, and additive spec/context version handling.
- `career_bot/campaigns/runner.py` — add deterministic review/continue-preferred transitions using existing state enum.
- `career_bot/campaigns/parent_evaluator.py` — reuse target evaluation output instead of maintaining incompatible factor semantics.
- `career_bot/campaigns/__init__.py` — export new public campaign-domain types/services.
- `main.py` — instantiate campaign service, expose `/api/campaigns*`, serve `/campaigns` and campaign assets.
- `public/index.html` — add top-level navigation link to `/campaigns`.
- `public/styles.css` — only shared navigation styles that truly belong to all pages.
- `tests/test_campaign_models.py`
- `tests/test_campaign_store.py`
- `tests/test_campaign_runner.py`
- `tests/test_legacy_scanner.py`
- `tests/test_legacy_race_planner.py`

Do not move turn-runner behavior into campaign code. Do not duplicate `CampaignStore`, `CampaignRunner`, affinity calculation, `scan_legacy_loop_pools`, `build_shared_g1_agenda`, or veteran inventory decoding.

---

### Task 1: Extend campaign specification models without breaking existing campaigns

**Files:**
- Modify: `career_bot/campaigns/models.py`
- Test: `tests/test_campaign_models.py`

- [ ] **Step 1: Write failing tests for the new Web campaign spec fields and backward compatibility**

Add tests that cover a required Final Uma, mixed blue/pink targets, required/preferred priorities, four loop members, manual deck IDs, rental policy, auto-use policy, and loading the old minimal `ParentCampaignSpec` shape.

```python
from career_bot.campaigns.models import ParentCampaignSpec


def test_campaign_spec_accepts_web_parent_planner_fields():
    spec = ParentCampaignSpec.model_validate({
        "account": "acct01",
        "goal": {
            "purpose": "parent",
            "target_factors": [],
        },
        "strategy": {
            "preset_name": "campaign-base",
            "maximum_runs": 100,
            "maximum_runtime_hours": 72,
            "tp_mode": "wait",
        },
        "final_uma": {"card_id": 100401},
        "spark_targets": [
            {"category": "blue", "name": "stamina", "minimum_stars": 9, "priority": "required"},
            {"category": "pink", "name": "long", "minimum_stars": 6, "priority": "required"},
            {"category": "pink", "name": "medium", "minimum_stars": 3, "priority": "preferred"},
        ],
        "final_parent": {"chara_id": 1007, "trained_chara_id": 0},
        "loop_members": [
            {"chara_id": 1001, "deck_id": 1},
            {"chara_id": 1002, "deck_id": 2},
            {"chara_id": 1003, "deck_id": 3},
            {"chara_id": 1004, "deck_id": 4},
        ],
        "options": {"allow_rental": True, "auto_use_best_veteran": False},
    })

    assert spec.final_uma.card_id == 100401
    assert spec.spark_targets[0].minimum_stars == 9
    assert spec.spark_targets[2].priority.value == "preferred"
    assert [row.deck_id for row in spec.loop_members] == [1, 2, 3, 4]
    assert spec.options.allow_rental is True


def test_old_campaign_spec_still_loads_with_web_fields_defaulted(sample_spec_dict):
    spec = ParentCampaignSpec.model_validate(sample_spec_dict)
    assert spec.final_uma.card_id == 0
    assert spec.spark_targets == []
    assert spec.loop_members == []
    assert spec.options.allow_rental is False
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
pytest tests/test_campaign_models.py -q
```

Expected: FAIL because `final_uma`, `spark_targets`, `final_parent`, `loop_members`, and `options` do not yet exist.

- [ ] **Step 3: Add normalized enums and Pydantic models**

Add models with `extra="forbid"` and normalized names:

```python
class SparkCategory(str, Enum):
    BLUE = "blue"
    PINK = "pink"


class SparkPriority(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"


class CampaignSparkTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: SparkCategory
    name: str
    minimum_stars: int = Field(ge=1, le=9)
    priority: SparkPriority = SparkPriority.REQUIRED

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            raise ValueError("spark target name is required")
        return normalized


class FinalUmaSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: int = Field(default=0, ge=0)


class FinalParentTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chara_id: int = Field(default=0, ge=0)
    trained_chara_id: int = Field(default=0, ge=0)


class CampaignLoopMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chara_id: int = Field(gt=0)
    deck_id: int = Field(default=0, ge=0, le=10)
    pinned: bool = False


class CampaignOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow_rental: bool = False
    auto_use_best_veteran: bool = False
```

Extend `ParentCampaignSpec` additively:

```python
class ParentCampaignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: str
    goal: ParentGoal
    strategy: ParentStrategy
    trainee: TraineeSelectionPolicy = Field(default_factory=TraineeSelectionPolicy)
    deck: DeckSelectionPolicy = Field(default_factory=DeckSelectionPolicy)
    final_uma: FinalUmaSelection = Field(default_factory=FinalUmaSelection)
    spark_targets: list[CampaignSparkTarget] = Field(default_factory=list)
    final_parent: FinalParentTarget = Field(default_factory=FinalParentTarget)
    loop_members: list[CampaignLoopMember] = Field(default_factory=list)
    options: CampaignOptions = Field(default_factory=CampaignOptions)
    spec_version: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def validate_loop_members(self) -> "ParentCampaignSpec":
        if self.loop_members and len(self.loop_members) != 4:
            raise ValueError("loop_members must contain exactly four members when configured")
        ids = [row.chara_id for row in self.loop_members]
        if len(ids) != len(set(ids)):
            raise ValueError("loop_members cannot contain duplicate characters")
        return self
```

Do not require `final_uma` for old MCP campaign specs at model-parse time. Enforce the Web planner requirement at the Web create/recommend boundary.

- [ ] **Step 4: Run model tests**

Run:

```bash
pytest tests/test_campaign_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add career_bot/campaigns/models.py tests/test_campaign_models.py
git commit -m "feat(campaigns): extend planner spec"
```

---

### Task 2: Implement generic blue/pink target evaluation

**Files:**
- Create: `career_bot/campaigns/targets.py`
- Create: `tests/test_campaign_targets.py`
- Modify: `career_bot/campaigns/parent_evaluator.py`

- [ ] **Step 1: Write failing tests for `Stamina >= 9`, `Long >= 6`, and required/preferred semantics**

```python
from career_bot.campaigns.models import CampaignSparkTarget
from career_bot.campaigns.targets import evaluate_spark_targets


def targets():
    return [
        CampaignSparkTarget(category="blue", name="stamina", minimum_stars=9, priority="required"),
        CampaignSparkTarget(category="pink", name="long", minimum_stars=6, priority="required"),
        CampaignSparkTarget(category="pink", name="medium", minimum_stars=3, priority="preferred"),
    ]


def test_required_targets_gate_completion_but_preferred_does_not():
    result = evaluate_spark_targets(
        targets(),
        {
            ("blue", "stamina"): 9,
            ("pink", "long"): 6,
            ("pink", "medium"): 0,
        },
    )
    assert result["required_complete"] is True
    assert result["preferred_complete"] is False
    assert result["rows"][0]["ratio"] == 1.0


def test_target_progress_is_capped_at_one_for_scoring():
    result = evaluate_spark_targets(
        targets(),
        {("blue", "stamina"): 12, ("pink", "long"): 5},
    )
    assert result["required_complete"] is False
    assert result["required_progress"] == (1.0 + 5 / 6) / 2
```

- [ ] **Step 2: Run the tests and verify failure**

```bash
pytest tests/test_campaign_targets.py -q
```

Expected: FAIL because `campaigns.targets` does not exist.

- [ ] **Step 3: Implement target normalization and evaluation**

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import CampaignSparkTarget, SparkPriority


SparkKey = tuple[str, str]


def spark_key(category: Any, name: Any) -> SparkKey:
    return (str(category).strip().lower(), str(name).strip().lower())


def evaluate_spark_targets(
    targets: list[CampaignSparkTarget],
    totals: Mapping[SparkKey, int],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    required_ratios: list[float] = []
    preferred_ratios: list[float] = []

    for target in targets:
        key = spark_key(target.category.value, target.name)
        actual = max(0, int(totals.get(key, 0)))
        ratio = min(1.0, actual / target.minimum_stars)
        matched = actual >= target.minimum_stars
        row = {
            "category": target.category.value,
            "name": target.name,
            "minimum_stars": target.minimum_stars,
            "priority": target.priority.value,
            "actual_stars": actual,
            "ratio": ratio,
            "matched": matched,
        }
        rows.append(row)
        if target.priority is SparkPriority.REQUIRED:
            required_ratios.append(ratio)
        else:
            preferred_ratios.append(ratio)

    return {
        "rows": rows,
        "required_complete": all(row["matched"] for row in rows if row["priority"] == "required"),
        "preferred_complete": all(row["matched"] for row in rows if row["priority"] == "preferred"),
        "required_progress": sum(required_ratios) / len(required_ratios) if required_ratios else 1.0,
        "preferred_progress": sum(preferred_ratios) / len(preferred_ratios) if preferred_ratios else 1.0,
    }
```

Add one adapter in `parent_evaluator.py` so new campaign scoring can consume normalized target progress instead of inventing a second star-threshold implementation.

- [ ] **Step 4: Run focused tests**

```bash
pytest tests/test_campaign_targets.py tests/test_campaign_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add career_bot/campaigns/targets.py career_bot/campaigns/parent_evaluator.py tests/test_campaign_targets.py
git commit -m "feat(campaigns): evaluate spark targets"
```

---

### Task 3: Rank Final Parent candidates and enforce the final affinity gate

**Files:**
- Create: `career_bot/campaigns/final_setup.py`
- Create: `tests/test_campaign_final_setup.py`

- [ ] **Step 1: Write failing tests for exact affinity 150, rental policy, and existing veteran advantage**

```python
from career_bot.campaigns.final_setup import evaluate_final_setup, rank_final_parent_candidates


def test_affinity_exactly_150_is_ready():
    result = evaluate_final_setup(
        required_complete=True,
        pairings=[{"second_parent_id": 2, "affinity": 150, "rental": False}],
        allow_rental=False,
    )
    assert result["status"] == "READY"
    assert result["best_affinity"] == 150


def test_rental_only_setup_does_not_complete_when_disabled():
    result = evaluate_final_setup(
        required_complete=True,
        pairings=[{"second_parent_id": 9, "affinity": 180, "rental": True}],
        allow_rental=False,
    )
    assert result["status"] == "IN_PROGRESS"


def test_existing_near_complete_veteran_can_beat_theoretical_character():
    ranked = rank_final_parent_candidates([
        {"key": "existing", "required_progress": 0.95, "preferred_progress": 0.5, "best_affinity": 165, "existing": True, "effort": 0.1},
        {"key": "theoretical", "required_progress": 0.0, "preferred_progress": 0.0, "best_affinity": 195, "existing": False, "effort": 1.0},
    ])
    assert ranked[0]["key"] == "existing"
```

- [ ] **Step 2: Run and confirm failure**

```bash
pytest tests/test_campaign_final_setup.py -q
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement deterministic final setup evaluation and candidate scoring**

```python
from __future__ import annotations

from typing import Any


MIN_FINAL_AFFINITY = 150


def evaluate_final_setup(
    *,
    required_complete: bool,
    pairings: list[dict[str, Any]],
    allow_rental: bool,
) -> dict[str, Any]:
    allowed = [row for row in pairings if allow_rental or not bool(row.get("rental"))]
    allowed.sort(key=lambda row: (-int(row.get("affinity") or 0), bool(row.get("rental"))))
    best = allowed[0] if allowed else None
    best_affinity = int(best.get("affinity") or 0) if best else 0
    if not required_complete or best_affinity < MIN_FINAL_AFFINITY:
        status = "IN_PROGRESS"
    elif bool(best.get("rental")):
        status = "READY_WITH_RENTAL"
    else:
        status = "READY"
    return {"status": status, "best_affinity": best_affinity, "best_pairing": best}


def rank_final_parent_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        required = float(row.get("required_progress") or 0.0)
        preferred = float(row.get("preferred_progress") or 0.0)
        affinity = min(1.0, int(row.get("best_affinity") or 0) / 200.0)
        existing_bonus = 0.08 if row.get("existing") else 0.0
        effort_penalty = min(1.0, float(row.get("effort") or 0.0)) * 0.20
        score = required * 0.50 + preferred * 0.10 + affinity * 0.30 + existing_bonus - effort_penalty
        scored.append({**row, "score": score})
    return sorted(scored, key=lambda row: (-row["score"], str(row.get("key") or "")))
```

Keep the affinity callback outside this module. The caller supplies real pairings computed from the existing affinity calculator and current veteran inventory.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_campaign_final_setup.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add career_bot/campaigns/final_setup.py tests/test_campaign_final_setup.py
git commit -m "feat(campaigns): score final parent setups"
```

---

### Task 4: Add deterministic four-Uma rotation simulation

**Files:**
- Create: `career_bot/campaigns/rotation.py`
- Create: `tests/test_campaign_rotation.py`

- [ ] **Step 1: Write failing rotation and long-run simulation tests**

Use symbolic legacy IDs so the simulator can be tested without game payloads.

```python
from career_bot.campaigns.rotation import RotationState, advance_rotation


def test_completed_trainee_enters_future_lineage_and_oldest_node_falls_out():
    state = RotationState.bootstrap([1001, 1002, 1003, 1004])
    next_state = advance_rotation(state, produced_legacy_id="legacy-a")
    assert next_state.run_index == 1
    assert next_state.next_trainee_chara_id == 1002
    assert "legacy-a" in next_state.available_legacy_ids


def test_twenty_rotations_only_use_the_four_loop_characters_as_trainees():
    state = RotationState.bootstrap([1001, 1002, 1003, 1004])
    seen = []
    for index in range(20):
        seen.append(state.next_trainee_chara_id)
        state = advance_rotation(state, produced_legacy_id=f"legacy-{index}")
    assert seen == [1001, 1002, 1003, 1004] * 5
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest tests/test_campaign_rotation.py -q
```

Expected: FAIL because `rotation.py` does not exist.

- [ ] **Step 3: Implement an immutable serializable rotation state**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RotationState:
    loop_chara_ids: tuple[int, int, int, int]
    run_index: int
    produced: tuple[tuple[int, str], ...]

    @classmethod
    def bootstrap(cls, chara_ids: list[int]) -> "RotationState":
        if len(chara_ids) != 4 or len(set(chara_ids)) != 4:
            raise ValueError("rotation requires four unique characters")
        return cls(tuple(int(value) for value in chara_ids), 0, ())

    @property
    def next_trainee_chara_id(self) -> int:
        return self.loop_chara_ids[self.run_index % 4]

    @property
    def available_legacy_ids(self) -> list[str]:
        return [legacy_id for _chara_id, legacy_id in self.produced]

    def to_dict(self) -> dict:
        return asdict(self)


def advance_rotation(state: RotationState, *, produced_legacy_id: str) -> RotationState:
    produced = [*state.produced, (state.next_trainee_chara_id, str(produced_legacy_id))]
    return RotationState(state.loop_chara_ids, state.run_index + 1, tuple(produced[-8:]))
```

The initial implementation intentionally models campaign ordering and bounded recent lineage inventory, not game-specific parent slot selection. Concrete parent/grandparent role selection belongs to the resolver/planner where affinity and actual veteran trees are available.

- [ ] **Step 4: Run simulation tests**

```bash
pytest tests/test_campaign_rotation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add career_bot/campaigns/rotation.py tests/test_campaign_rotation.py
git commit -m "feat(campaigns): simulate legacy rotation"
```

---

### Task 5: Build Final Parent and assisted four-Uma recommendation services

**Files:**
- Create: `career_bot/campaigns/planner.py`
- Create: `tests/test_campaign_planner.py`
- Modify: `tests/test_legacy_scanner.py`

- [ ] **Step 1: Write failing tests for three Final Parent recommendations, owned-first loop results, and pinned recomputation**

```python
from career_bot.campaigns.planner import CampaignPlanner


def test_final_parent_recommendation_returns_top_three(planner_fixture):
    result = planner_fixture.recommend_final_parents(limit=3)
    assert len(result) == 3
    assert result == sorted(result, key=lambda row: row["score"], reverse=True)


def test_loop_recommendation_uses_owned_characters_and_preserves_pins(planner_fixture):
    result = planner_fixture.recommend_loops(pinned_chara_ids={1001}, limit=3)
    assert result
    assert all(1001 in row["chara_ids"] for row in result)
    assert all(row["owned"] is True for row in result)
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest tests/test_campaign_planner.py tests/test_legacy_scanner.py -q
```

Expected: FAIL because `CampaignPlanner` does not exist.

- [ ] **Step 3: Implement a planner that composes existing helpers**

The constructor receives data and callbacks instead of importing `main.py` globals:

```python
class CampaignPlanner:
    def __init__(
        self,
        *,
        owned_chara_ids: set[int],
        veteran_records: list[dict],
        display_by_id: dict[int, dict],
        g1_saddle_ids: set[int],
        race_rows: list[dict],
        affinity_for_pair,
    ) -> None:
        self.owned_chara_ids = owned_chara_ids
        self.veteran_records = veteran_records
        self.display_by_id = display_by_id
        self.g1_saddle_ids = g1_saddle_ids
        self.race_rows = race_rows
        self.affinity_for_pair = affinity_for_pair
```

`recommend_final_parents()` must:

1. summarize existing veterans with `veteran_inventory` helpers;
2. evaluate campaign target progress with `targets.evaluate_spark_targets`;
3. enumerate allowed second parents and compute actual final affinity through the injected callback;
4. call `final_setup.rank_final_parent_candidates`;
5. collapse duplicate character recommendations while preserving a strong concrete existing veteran;
6. return exactly the top requested rows.

`recommend_loops()` must:

1. call `scan_legacy_loop_pools` on owned records;
2. discard loops missing pinned characters;
3. enrich each loop with a shared G1 agenda from `build_shared_g1_agenda`;
4. add Final Uma/final-parent compatibility components;
5. expose optional `ideal_upgrades` separately rather than mixing non-owned characters into runnable loop results.

Use a named score breakdown in the return payload:

```python
{
    "score": total,
    "score_breakdown": {
        "mutual_compatibility": mutual,
        "stable_affinity": stable,
        "shared_g1": shared_g1,
        "style_alignment": style,
        "distance_overlap": distance,
        "final_target_fit": final_fit,
    },
}
```

- [ ] **Step 4: Run planner and scanner tests**

```bash
pytest tests/test_campaign_planner.py tests/test_legacy_scanner.py tests/test_legacy_race_planner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add career_bot/campaigns/planner.py tests/test_campaign_planner.py tests/test_legacy_scanner.py
git commit -m "feat(campaigns): recommend parent loops"
```

---

### Task 6: Implement pre-run legacy resolution with locked/flexible and rental policies

**Files:**
- Create: `career_bot/campaigns/resolver.py`
- Create: `tests/test_campaign_resolver.py`

- [ ] **Step 1: Write failing tests for locked slots, flexible upgrades, rental disabled, and deterministic tie-breaking**

```python
from career_bot.campaigns.resolver import LegacyResolver, LegacySlot


def test_locked_slot_keeps_specific_campaign_legacy():
    resolver = LegacyResolver(allow_rental=False)
    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="LOCKED", trained_chara_id=41),
        candidates=[{"trained_chara_id": 41, "score": 10}, {"trained_chara_id": 99, "score": 999}],
    )
    assert result["trained_chara_id"] == 41


def test_flexible_slot_uses_better_owned_candidate():
    resolver = LegacyResolver(allow_rental=False)
    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="FLEXIBLE", trained_chara_id=41),
        candidates=[
            {"trained_chara_id": 41, "score": 10, "rental": False},
            {"trained_chara_id": 99, "score": 20, "rental": False},
        ],
    )
    assert result["trained_chara_id"] == 99
    assert result["replacement"] is True


def test_rental_candidate_is_filtered_when_disabled():
    resolver = LegacyResolver(allow_rental=False)
    result = resolver.resolve_slot(
        LegacySlot(role="parent2", mode="FLEXIBLE", trained_chara_id=0),
        candidates=[{"trained_chara_id": 9, "score": 100, "rental": True}],
    )
    assert result["status"] == "UNRESOLVED"
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest tests/test_campaign_resolver.py -q
```

Expected: FAIL because `resolver.py` does not exist.

- [ ] **Step 3: Implement deterministic resolution and audit reasons**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LegacySlot:
    role: str
    mode: Literal["LOCKED", "FLEXIBLE"]
    trained_chara_id: int = 0


class LegacyResolver:
    def __init__(self, *, allow_rental: bool) -> None:
        self.allow_rental = allow_rental

    def resolve_slot(self, slot: LegacySlot, *, candidates: list[dict]) -> dict:
        allowed = [row for row in candidates if self.allow_rental or not bool(row.get("rental"))]
        if slot.mode == "LOCKED":
            for row in allowed:
                if int(row.get("trained_chara_id") or 0) == slot.trained_chara_id:
                    return {**row, "status": "RESOLVED", "replacement": False, "reason": "locked campaign lineage"}
            return {"status": "UNRESOLVED", "role": slot.role, "reason": "locked veteran unavailable"}

        ranked = sorted(
            allowed,
            key=lambda row: (-float(row.get("score") or 0.0), int(row.get("trained_chara_id") or 0)),
        )
        if not ranked:
            return {"status": "UNRESOLVED", "role": slot.role, "reason": "no allowed veteran candidate"}
        best = ranked[0]
        old_id = int(slot.trained_chara_id or 0)
        new_id = int(best.get("trained_chara_id") or 0)
        return {
            **best,
            "status": "RESOLVED",
            "replacement": bool(old_id and old_id != new_id),
            "previous_trained_chara_id": old_id,
            "reason": best.get("reason") or "highest deterministic resolver score",
        }
```

The service layer will build candidate `score` from lineage continuity, projected affinity, required/preferred contribution, and shared G1 overlap. This module only enforces slot policy and deterministic selection.

- [ ] **Step 4: Run resolver tests**

```bash
pytest tests/test_campaign_resolver.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add career_bot/campaigns/resolver.py tests/test_campaign_resolver.py
git commit -m "feat(campaigns): resolve legacy slots"
```

---

### Task 7: Generate campaign presets and step-specific race overrides

**Files:**
- Create: `career_bot/campaigns/preset_policy.py`
- Create: `tests/test_campaign_preset_policy.py`
- Modify: `career_bot/campaigns/__init__.py`

- [ ] **Step 1: Write failing tests for manual deck preservation, blue-target stat emphasis, and race override separation**

```python
from career_bot.campaigns.preset_policy import build_campaign_base_preset, build_step_overrides


def test_base_preset_does_not_choose_or_mutate_deck():
    preset = build_campaign_base_preset(
        name="Campaign / A",
        running_style=3,
        scenario_id=4,
        spark_targets=[{"category": "blue", "name": "stamina", "minimum_stars": 9, "priority": "required"}],
        core_races=[10, 20],
        optional_races=[30],
    )
    assert "deck_id" not in preset
    assert preset["expect_stamina"] >= 1100


def test_step_overrides_replace_race_lists_without_mutating_base():
    overrides = build_step_overrides(core_races=[1, 2], optional_races=[3], parent_run=True)
    assert overrides == {"mandatory_race_list": [1, 2], "extra_race_list": [3], "parent_run": True}
```

- [ ] **Step 2: Run and confirm failure**

```bash
pytest tests/test_campaign_preset_policy.py -q
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement pure preset builders**

```python
from __future__ import annotations


def build_campaign_base_preset(*, name, running_style, scenario_id, spark_targets, core_races, optional_races):
    preset = {
        "name": str(name),
        "running_style": int(running_style),
        "scenario_id": int(scenario_id),
        "parent_run": True,
        "mandatory_race_list": list(core_races),
        "extra_race_list": list(optional_races),
    }
    for target in spark_targets:
        if target.get("category") != "blue":
            continue
        field = "wisdom" if target.get("name") == "wit" else target.get("name")
        if field in {"speed", "stamina", "power", "guts", "wisdom"}:
            preset[f"expect_{field}"] = max(int(preset.get(f"expect_{field}") or 0), 1100)
    return preset


def build_step_overrides(*, core_races, optional_races, parent_run=True):
    return {
        "mandatory_race_list": list(core_races),
        "extra_race_list": list(optional_races),
        "parent_run": bool(parent_run),
    }
```

The service saves base presets through the existing `PresetStore`; the builder itself remains pure and testable.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_campaign_preset_policy.py tests/test_campaign_runtime_overrides.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add career_bot/campaigns/preset_policy.py career_bot/campaigns/__init__.py tests/test_campaign_preset_policy.py
git commit -m "feat(campaigns): generate parent presets"
```

---

### Task 8: Extend durable campaign state for reviews, active-campaign enforcement, and preferred continuation

**Files:**
- Modify: `career_bot/campaigns/store.py`
- Modify: `career_bot/campaigns/runner.py`
- Modify: `tests/test_campaign_store.py`
- Modify: `tests/test_campaign_runner.py`

- [ ] **Step 1: Write failing store tests for one active campaign per account and review context persistence**

```python
def test_only_one_non_paused_active_campaign_per_account(tmp_path, sample_spec):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec, campaign_id="one")
    store.create(sample_spec, campaign_id="two")
    store.transition("one", CampaignState.READY)
    store.transition("two", CampaignState.READY)
    store.transition("one", CampaignState.STARTING_BOT)
    with pytest.raises(CampaignError, match="active campaign"):
        store.transition("two", CampaignState.STARTING_BOT)


def test_pending_review_survives_reload(tmp_path, sample_spec):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec, campaign_id="one")
    store.update_context("one", {"pending_review": {"type": "pre_run", "recommended_parent_id": 99}})
    reloaded = CampaignStore(tmp_path / "campaigns.sqlite3").get("one")
    assert reloaded["context"]["pending_review"]["recommended_parent_id"] == 99
```

- [ ] **Step 2: Write failing runner tests for pre-run review, post-run review, target-ready stop, and continue preferred**

Use the existing `NEEDS_USER_INPUT` state with `next_action` values rather than adding unnecessary enum states.

```python
def test_pre_run_review_uses_needs_user_input(runner, prepared_campaign):
    result = runner.require_user_input(prepared_campaign, next_action="approve_run", review={"type": "pre_run"})
    assert result["state"] == CampaignState.NEEDS_USER_INPUT.value
    assert result["next_action"] == "approve_run"


def test_continue_preferred_reopens_completed_target(runner, target_ready_campaign):
    result = runner.continue_for_preferred(target_ready_campaign)
    assert result["state"] == CampaignState.SELECTING_LINEAGE.value
    assert result["context"]["required_target_achieved"] is True
```

- [ ] **Step 3: Add store-level active-state guard inside the same transaction used by transition**

Define the active execution states once:

```python
ACTIVE_EXECUTION_STATES = {
    CampaignState.STARTING_BOT,
    CampaignState.WAITING_FOR_LOGIN,
    CampaignState.SELECTING_LINEAGE,
    CampaignState.RUNNING_CAREER,
    CampaignState.EVALUATING_RESULT,
    CampaignState.WAITING_FOR_TP,
    CampaignState.NEEDS_USER_INPUT,
}
```

Before transitioning into one of those states, query for another campaign on the same account in an active state and raise `CampaignError` if found. Keep `PAUSED`, `READY`, `DRAFT`, and terminal states outside the active set.

- [ ] **Step 4: Add runner helpers for structured review and preferred continuation**

```python
def require_user_input(self, campaign_id: str, *, next_action: str, review: dict) -> dict:
    self.store.update_context(campaign_id, {"pending_review": review})
    return self.store.transition(
        campaign_id,
        CampaignState.NEEDS_USER_INPUT,
        next_action=next_action,
    )


def continue_for_preferred(self, campaign_id: str) -> dict:
    current = self.store.get(campaign_id)
    if current["state"] != CampaignState.COMPLETED.value:
        raise InvalidTransition("continue preferred requires a completed campaign")
    self.store.update_context(
        campaign_id,
        {"required_target_achieved": True, "pending_review": None, "continue_preferred": True},
    )
    return self.store.reopen_completed(
        campaign_id,
        state=CampaignState.SELECTING_LINEAGE,
        next_action="prepare_next_run",
    )
```

Implement `reopen_completed()` as an explicit store method; do not weaken the general transition table for terminal states.

- [ ] **Step 5: Run store and runner tests**

```bash
pytest tests/test_campaign_store.py tests/test_campaign_runner.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add career_bot/campaigns/store.py career_bot/campaigns/runner.py tests/test_campaign_store.py tests/test_campaign_runner.py
git commit -m "feat(campaigns): persist review workflow"
```

---

### Task 9: Add a shared CampaignService that orchestrates planning without owning gameplay

**Files:**
- Create: `career_bot/campaigns/service.py`
- Create: `tests/test_campaign_service.py`
- Modify: `career_bot/campaigns/__init__.py`

- [ ] **Step 1: Write failing service tests for create, prepare review, auto-use, post-run evaluation, and completion**

Use fake dependencies so tests do not log into the game.

```python
class FakeRuntime:
    def snapshot(self):
        return {"owned_chara_ids": {1001, 1002, 1003, 1004}, "parents": [], "friend_veterans": []}


class FakeCareerGateway:
    def start(self, request):
        return {"success": True, "runner": {"running": True}, "request": request}


def test_prepare_next_run_requires_review_by_default(service, campaign_id):
    result = service.prepare_next_run(campaign_id)
    assert result["campaign"]["state"] == "NEEDS_USER_INPUT"
    assert result["campaign"]["next_action"] == "approve_run"


def test_auto_use_best_veteran_skips_pre_run_review(auto_service, auto_campaign_id):
    result = auto_service.prepare_next_run(auto_campaign_id)
    assert result["campaign"]["state"] == "SELECTING_LINEAGE"
    assert result["campaign"]["next_action"] == "start_career"


def test_required_targets_plus_affinity_150_complete_campaign(service, evaluating_campaign_id):
    result = service.record_completed_veteran(
        evaluating_campaign_id,
        candidate={"trained_chara_id": 77, "spark_totals": {("blue", "stamina"): 9, ("pink", "long"): 6}},
        final_pairings=[{"second_parent_id": 88, "affinity": 150, "rental": False}],
    )
    assert result["campaign"]["state"] == "COMPLETED"
    assert result["final_setup"]["status"] == "READY"
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest tests/test_campaign_service.py -q
```

Expected: FAIL because `CampaignService` does not exist.

- [ ] **Step 3: Implement `CampaignService` as a dependency-injected application layer**

Constructor:

```python
class CampaignService:
    def __init__(
        self,
        *,
        store,
        runner,
        preset_store,
        runtime_snapshot,
        affinity_for_setup,
        start_career,
    ) -> None:
        self.store = store
        self.runner = runner
        self.preset_store = preset_store
        self.runtime_snapshot = runtime_snapshot
        self.affinity_for_setup = affinity_for_setup
        self.start_career = start_career
```

Public methods required by Web and later reusable by MCP:

```python
list_campaigns(account)
get_campaign(campaign_id)
recommend_final_parents(request)
recommend_loops(request)
create_campaign(spec)
activate(campaign_id)
pause(campaign_id)
resume(campaign_id)
prepare_next_run(campaign_id)
approve_run(campaign_id, selection_override=None)
select_candidate(campaign_id, candidate_id)
record_completed_veteran(campaign_id, candidate, final_pairings)
continue_for_preferred(campaign_id)
cancel(campaign_id, reason="")
```

`create_campaign()` must reject Web planner specs unless `final_uma.card_id > 0`, at least one spark target is `required`, exactly four loop members are selected, and every loop member has a manual `deck_id` in `1..10`. Legacy MCP specs remain loadable at the model layer; this stricter validation belongs to the Web/application workflow.

`prepare_next_run()` must:

1. load persisted campaign and fresh runtime snapshot;
2. restore/advance `RotationState` from `context_json`;
3. build resolver candidates from current owned/campaign/rental inventory;
4. resolve slots;
5. build current shared G1 step overrides;
6. persist `prepared_run` and `pending_review` before returning;
7. if `auto_use_best_veteran` is false, call `runner.require_user_input(..., next_action="approve_run")`;
8. otherwise persist an audit event for every automatic replacement and set `next_action="start_career"`.

`approve_run()` must only delegate one prepared request to the existing career start gateway. It must never run career turns itself.

`record_completed_veteran()` must:

1. evaluate targets;
2. evaluate final setup;
3. compare against the selected/current best candidate;
4. auto-reject dominated results;
5. require post-run review for meaningful trade-offs;
6. complete at `READY` or allowed `READY_WITH_RENTAL`;
7. otherwise advance rotation and return to `SELECTING_LINEAGE`.

- [ ] **Step 4: Run service tests**

```bash
pytest tests/test_campaign_service.py tests/test_campaign_targets.py tests/test_campaign_final_setup.py tests/test_campaign_resolver.py tests/test_campaign_rotation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add career_bot/campaigns/service.py career_bot/campaigns/__init__.py tests/test_campaign_service.py
git commit -m "feat(campaigns): orchestrate campaign runs"
```

---

### Task 10: Expose thin Web campaign APIs and the `/campaigns` page route

**Files:**
- Modify: `main.py`
- Create: `tests/test_campaign_web_api.py`

Before modifying `main.py`, read `.claude/rules/server.md`.

- [ ] **Step 1: Write failing API tests with a fake campaign service**

Use FastAPI dependency/module monkeypatching rather than real game login.

Test these routes:

```text
GET    /api/campaigns
POST   /api/campaigns/recommend-final-parents
POST   /api/campaigns/recommend-loop
POST   /api/campaigns
GET    /api/campaigns/{id}
POST   /api/campaigns/{id}/activate
POST   /api/campaigns/{id}/pause
POST   /api/campaigns/{id}/resume
POST   /api/campaigns/{id}/prepare-next-run
POST   /api/campaigns/{id}/approve-run
POST   /api/campaigns/{id}/select-candidate
POST   /api/campaigns/{id}/continue-preferred
POST   /api/campaigns/{id}/cancel
```

Representative test:

```python
def test_campaign_create_delegates_to_service(client, fake_campaign_service):
    response = client.post("/api/campaigns", json={"spec": valid_web_spec()})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert fake_campaign_service.calls[-1][0] == "create_campaign"
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest tests/test_campaign_web_api.py -q
```

Expected: FAIL with route-not-found responses.

- [ ] **Step 3: Instantiate campaign persistence and service once near existing stores**

Use the same default database contract as MCP:

```python
campaign_store = CampaignStore(
    os.environ.get("SWEEPY_CAMPAIGNS_DB")
    or base_dir / "uma_runtime" / "campaigns.sqlite3"
)
campaign_runner = CampaignRunner(campaign_store)
```

Build a `CampaignService` with adapters around existing in-process runtime state:

- runtime snapshot from `active_dashboard_data`, `active_parent_full`, current friends/rentals;
- affinity callback using existing `affinity_calc.calculate_affinity` and master data path;
- preset saving via existing `preset_store`;
- career start via the existing campaign-safe request preparation path, not a duplicate HTTP self-call.

- [ ] **Step 4: Add Pydantic request wrappers and thin endpoints**

Example:

```python
class CampaignCreateRequest(BaseModel):
    spec: ParentCampaignSpec


@app.post("/api/campaigns")
async def create_campaign(req: CampaignCreateRequest):
    return {"success": True, "campaign": campaign_service.create_campaign(req.spec)}
```

Every endpoint catches known campaign-domain exceptions and converts them to `HTTPException(status_code=409 or 422, detail=str(exc))`; do not swallow unexpected exceptions.

- [ ] **Step 5: Serve the dedicated page and assets**

```python
@app.get("/campaigns", response_class=HTMLResponse)
async def campaigns_page():
    path = base_dir / "public" / "campaigns.html"
    return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/campaigns.js")
async def campaigns_js():
    path = base_dir / "public" / "campaigns.js"
    return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/campaigns.css")
async def campaigns_css():
    path = base_dir / "public" / "campaigns.css"
    return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-cache"})
```

- [ ] **Step 6: Run API tests and focused existing tests**

```bash
pytest tests/test_campaign_web_api.py tests/test_campaign_store.py tests/test_campaign_runner.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_campaign_web_api.py
git commit -m "feat(api): expose parent campaigns"
```

---

### Task 11: Build the dedicated Campaigns Web UI

**Files:**
- Create: `public/campaigns.html`
- Create: `public/campaigns.js`
- Create: `public/campaigns.css`
- Modify: `public/index.html`
- Modify: `public/styles.css`

Before modifying `public/**`, read `.claude/rules/frontend.md`.

- [ ] **Step 1: Create page shell with top-level navigation and stable element IDs**

`public/campaigns.html` must load global styles first, then page styles:

```html
<link rel="stylesheet" href="/styles.css">
<link rel="stylesheet" href="/campaigns.css">
```

Required top-level sections:

```html
<nav class="top-nav">
  <a href="/">Dashboard</a>
  <a href="/veteran">Veterans</a>
  <a href="/dailies">Dailies</a>
  <a href="/campaigns" aria-current="page">Campaigns</a>
</nav>

<main id="campaign-app">
  <section id="campaign-list-view"></section>
  <section id="campaign-create-view" hidden></section>
  <section id="campaign-detail-view" hidden></section>
</main>
<script src="/campaigns.js"></script>
```

Add a `Campaigns` link to the existing main page navigation without changing existing dashboard route behavior.

- [ ] **Step 2: Implement a small page-local state store and API helper**

```javascript
const state = {
    campaigns: [],
    selectedCampaign: null,
    finalParentRecommendations: [],
    loopRecommendations: [],
    draft: {
        finalUmaCardId: 0,
        sparkTargets: [],
        selectedFinalParent: null,
        selectedLoop: null,
        deckAssignments: {},
        options: { allowRental: false, autoUseBestVeteran: false },
    },
};

async function apiJson(path, options = {}) {
    const response = await fetch(path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.success === false) {
        throw new Error(body.detail || `Request failed (${response.status})`);
    }
    return body;
}
```

Do not import a framework.

- [ ] **Step 3: Implement campaign list and create flow**

The create flow must enforce this order in the UI:

1. select Final Uma;
2. add blue/pink target rows with minimum stars and required/preferred priority;
3. request three Final Parent recommendations;
4. choose one;
5. request loop recommendations;
6. pin/replace/select loop;
7. assign a deck ID to each loop member;
8. set rental and auto-use options;
9. preview and save.

Target row payload must be emitted exactly as:

```javascript
{
    category: "blue" | "pink",
    name: "stamina" | "long" | "...",
    minimum_stars: Number(value),
    priority: "required" | "preferred",
}
```

- [ ] **Step 4: Implement active campaign dashboard and review surfaces**

Render:

- Final Uma and Final Parent;
- required/preferred progress bars;
- current rotation and next trainee;
- current lineage/resolved parent choices;
- projected affinity;
- race agenda grouped `CORE`, `OPTIONAL`, `DEFERABLE`;
- current state and `next_action`;
- recent events;
- candidate history.

For `NEEDS_USER_INPUT`:

```javascript
if (campaign.state === "NEEDS_USER_INPUT" && campaign.next_action === "approve_run") {
    renderPreRunReview(campaign.context.pending_review);
}
if (campaign.state === "NEEDS_USER_INPUT" && campaign.next_action === "select_candidate") {
    renderPostRunReview(campaign.context.pending_review);
}
```

Actions must call the matching API endpoint and then reload the campaign from the server. The browser must not locally invent state transitions.

- [ ] **Step 5: Add responsive page-specific CSS**

Use existing CSS variables. Keep layout in `campaigns.css`:

```css
.campaign-layout {
    display: grid;
    grid-template-columns: minmax(18rem, 24rem) minmax(0, 1fr);
    gap: 1rem;
}

@media (max-width: 960px) {
    .campaign-layout {
        grid-template-columns: 1fr;
    }
}
```

Do not add inline style blobs to generated JavaScript HTML unless the value is genuinely dynamic.

- [ ] **Step 6: Manual browser verification**

Run the app normally, then verify:

```text
/campaigns loads directly
refresh on /campaigns still loads the page
campaign list renders
create flow blocks recommendation until Final Uma exists
required/preferred target rows serialize correctly
pre-run review cannot start a run without approval when auto-use is off
auto-use campaign skips approval and records replacement reasons
completed campaign shows READY or READY WITH RENTAL
CONTINUE FOR PREFERRED returns the campaign to active planning
```

- [ ] **Step 7: Commit**

```bash
git add public/campaigns.html public/campaigns.js public/campaigns.css public/index.html public/styles.css
git commit -m "feat(web): add campaign planner page"
```

---

### Task 12: Add restart recovery and current-career reconciliation

**Files:**
- Modify: `career_bot/campaigns/service.py`
- Modify: `tests/test_campaign_service.py`

- [ ] **Step 1: Write failing tests for matching and mismatched active career recovery**

```python
def test_reconcile_matching_active_career_resumes_running_state(service, running_campaign_id):
    result = service.reconcile_runtime(
        running_campaign_id,
        current_career={"active": True, "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11},
    )
    assert result["state"] == "RUNNING_CAREER"


def test_reconcile_mismatched_active_career_pauses_campaign(service, running_campaign_id):
    result = service.reconcile_runtime(
        running_campaign_id,
        current_career={"active": True, "card_id": 999999, "deck_id": 9},
    )
    assert result["state"] == "PAUSED"
    assert "does not match" in result["error"].lower()
```

- [ ] **Step 2: Implement explicit prepared-run matching**

Compare only persisted fields that identify the planned run:

```python
def _career_matches_prepared_run(current_career: dict, prepared_run: dict) -> bool:
    expected = prepared_run.get("career_request") or {}
    return (
        int(current_career.get("card_id") or 0) == int(expected.get("card_id") or 0)
        and int(current_career.get("deck_id") or 0) == int(expected.get("deck_id") or 0)
        and int(current_career.get("parent_id_1") or 0) == int(expected.get("parent_id_1") or 0)
        and int(current_career.get("parent_id_2") or 0) == int(expected.get("parent_id_2") or 0)
    )
```

When mismatch occurs, pause and persist a recovery event. Do not delete or restart the active career.

- [ ] **Step 3: Implement missing-veteran recovery policy**

- `FLEXIBLE` missing slot: call resolver again.
- `LOCKED` missing slot: transition to `NEEDS_USER_INPUT` with `next_action="resolve_missing_locked_veteran"`.
- unavailable rental: try another allowed rental or owned candidate; if none preserve the objective, require review.

- [ ] **Step 4: Run service recovery tests**

```bash
pytest tests/test_campaign_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add career_bot/campaigns/service.py tests/test_campaign_service.py
git commit -m "fix(campaigns): recover persisted runs safely"
```

---

### Task 13: Run full campaign regression suite and verify privacy/storage behavior

**Files:**
- Modify only if failures reveal necessary fixes in files already covered above.

- [ ] **Step 1: Run all campaign-domain tests**

```bash
pytest \
  tests/test_campaign_models.py \
  tests/test_campaign_targets.py \
  tests/test_campaign_final_setup.py \
  tests/test_campaign_rotation.py \
  tests/test_campaign_planner.py \
  tests/test_campaign_resolver.py \
  tests/test_campaign_preset_policy.py \
  tests/test_campaign_store.py \
  tests/test_campaign_runner.py \
  tests/test_campaign_service.py \
  tests/test_campaign_web_api.py \
  tests/test_legacy_scanner.py \
  tests/test_legacy_race_planner.py \
  -q
```

Expected: all PASS.

- [ ] **Step 2: Run the existing broader test suite**

```bash
pytest -q
```

Expected: all PASS. Any pre-existing unrelated failure must be documented with exact test name and output before proceeding.

- [ ] **Step 3: Inspect SQLite persistence manually with a temporary DB**

Run the campaign store tests or a local development campaign against a temporary `SWEEPY_CAMPAIGNS_DB`, then verify stored campaign JSON contains no auth/session material:

```bash
sqlite3 /tmp/sweepy-campaigns.sqlite3 \
  "select campaign_id, account, state, spec_json, context_json from campaigns limit 5;"
```

Expected: durable campaign metadata only; no `sid`, token, cookie, device ID, viewer ID, or raw private API payload.

- [ ] **Step 4: Run privacy and staged-diff scan before final commit**

```bash
git diff --check
git status --short
git diff --cached --stat
rg -n '/home/|viewer_id|sid|steam_session_ticket|auth_key|password' \
  career_bot/campaigns public/campaigns.* tests/test_campaign_* docs/superpowers/plans/2026-07-16-parent-campaign-planner.md
```

Expected: no real private identifiers or credentials in tracked additions.

- [ ] **Step 5: Final integration commit if verification fixes were needed**

```bash
git add career_bot/campaigns main.py public tests
git commit -m "test(campaigns): verify planner workflow"
```

Skip this commit when Task 13 produces no code changes.

---

## Implementation Order Rationale

1. Models first so every later module shares one contract.
2. Pure target/final-setup/rotation functions next because they are cheap to test and define campaign semantics.
3. Planner, resolver, and preset policy then compose existing game-domain helpers without Web coupling.
4. Store/runner changes follow once the new workflow semantics are concrete.
5. `CampaignService` becomes the single application boundary before adding HTTP routes.
6. Web API and UI come only after the workflow is testable headlessly.
7. Recovery is implemented after normal execution works, using the same persisted prepared-run contract.
8. Full verification comes last.

## Explicit Non-Goals During Implementation

Do not:

- add white-skill targets;
- auto-select support decks;
- require all four loop members to become 9-star parents;
- require both final parents to be campaign-produced;
- create a generic workflow engine;
- duplicate affinity logic;
- duplicate the career runner;
- silently use rental when `allow_rental` is false;
- complete at affinity 149;
- delete rejected veterans;
- let browser state become the source of truth for campaign transitions.
