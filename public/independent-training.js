'use strict';

const state = {
    bootstrap: null,
    status: null,
    factorTargets: [],
    privateFriends: [],
    presets: [],
    skills: [],
    prioritySkillIds: [],
    finalSkillIds: [],
    skillFilters: {
        prioritySkillIds: {style: null, distance: null, surface: null, color: null},
        finalSkillIds: {style: null, distance: null, surface: null, color: null},
    },
    raceData: [],
    selectedRaceIds: [],
    objectiveRaceIds: [],
    objectiveRequestController: null,
    objectiveRequestGeneration: 0,
    pollBusy: false,
};

const byId = (id) => document.getElementById(id);
const els = {
    message: byId('independent-message'),
    account: byId('independent-account'),
    executor: byId('executor-state'),
    active: byId('active-run-content'),
    queue: byId('queue-list'),
    results: byId('recent-results'),
    form: byId('independent-setup-form'),
    trainee: byId('trainee-select'),
    parentOne: byId('parent-one-select'),
    parentTwo: byId('parent-two-select'),
    parentOnePreview: byId('parent-one-preview'),
    parentTwoPreview: byId('parent-two-preview'),
    deck: byId('deck-select'),
    deckPreview: byId('deck-preview'),
    friend: byId('friend-support-select'),
    friendPreview: byId('friend-support-preview'),
    preset: byId('independent-preset-select'),
    presetName: byId('independent-preset-name'),
    savePreset: byId('save-independent-preset'),
    loadPreset: byId('load-independent-preset'),
    deletePreset: byId('delete-independent-preset'),
    prioritySkillSearch: byId('priority-skill-search'),
    prioritySkillFilters: byId('priority-skill-filters'),
    prioritySkillSelection: byId('priority-skill-selection'),
    prioritySkillResults: byId('priority-skill-results'),
    finalSkillSearch: byId('final-skill-search'),
    finalSkillFilters: byId('final-skill-filters'),
    finalSkillSelection: byId('final-skill-selection'),
    finalSkillResults: byId('final-skill-results'),
    raceSchedule: byId('race-schedule-select'),
    raceOptions: byId('independent-race-options'),
    racePopup: byId('independent-race-popup-overlay'),
    racePopupTitle: byId('independent-race-popup-title'),
    racePopupBody: byId('independent-race-popup-body'),
    raceCount: byId('race-selection-count'),
    targets: byId('factor-targets'),
    reroll: byId('factor-reroll-enabled'),
    detectedTpCost: byId('detected-tp-cost'),
};

function escapeHtml(value) {
    return String(value ?? '').replace(
        /[&<>'"]/g,
        (character) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;',
        })[character],
    );
}

function showMessage(message = '', kind = '') {
    els.message.textContent = message;
    els.message.className = `independent-message${kind ? ` is-${kind}` : ''}`;
}

async function apiJson(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: options.body
                ? {'Content-Type': 'application/json', ...(options.headers || {})}
                : options.headers,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.success === false) {
            throw new Error(data.detail || `Request failed (${response.status})`);
        }
        return data;
    } catch (error) {
        if (error.name !== 'AbortError') {
            showMessage(error.message || 'Request failed', 'error');
        }
        throw error;
    }
}

function asPositiveInt(value, label) {
    const number = Number(value);
    if (!Number.isInteger(number) || number <= 0) {
        throw new Error(`${label} must be a positive integer.`);
    }
    return number;
}

function labelFor(row, fallback) {
    return String(
        row?.name
        || row?.chara_name
        || row?.card_name
        || row?.card_id
        || row?.trained_chara_id
        || fallback,
    );
}

function traineeId(row) {
    return Number(row?.card_id || row?.id || 0);
}

function parentId(row) {
    return Number(row?.trained_chara_id || row?.instance_id || row?.id || 0);
}

function deckId(row) {
    return Number(row?.id || row?.deck_id || 0);
}

function ownSparks(parent) {
    return Array.isArray(parent?.tree?.self?.factors)
        ? parent.tree.self.factors
        : (Array.isArray(parent?.factors) ? parent.factors : []);
}

function sparkGroup(factor) {
    const category = String(factor?.category || '').toLowerCase();
    if (['blue', 'stat'].includes(category)) return 'Blue';
    if (['pink', 'aptitude'].includes(category)) return 'Red';
    if (['green', 'unique'].includes(category)) return 'Green';
    return 'White';
}

function sparkLabel(factor) {
    const stars = Math.max(0, Number(factor?.stars || 0));
    return `${factor?.name || 'Unknown'} ${'★'.repeat(stars) || '0★'}`;
}

const SPARK_GROUP_ORDER = {Blue: 0, Red: 1, Green: 2, White: 3};

function lineageNodes(parent) {
    const tree = parent?.tree || {};
    return [
        {key: 'self', role: 'Parent', node: {...(tree.self || {}), factors: ownSparks(parent)}},
        {key: 'p1', role: 'GP1', node: tree.p1 || {}},
        {key: 'p2', role: 'GP2', node: tree.p2 || {}},
    ];
}

function lineageRollup(parent) {
    const totals = new Map();
    lineageNodes(parent).forEach(({node}) => {
        (node.factors || []).forEach((factor) => {
            const group = sparkGroup(factor);
            const name = String(factor?.name || 'Unknown');
            const key = `${group}:${name.toLowerCase()}`;
            const entry = totals.get(key) || {group, name, stars: 0};
            entry.stars += Math.max(0, Number(factor?.stars || 0));
            totals.set(key, entry);
        });
    });
    return [...totals.values()].sort((left, right) => (
        SPARK_GROUP_ORDER[left.group] - SPARK_GROUP_ORDER[right.group]
        || right.stars - left.stars
        || left.name.localeCompare(right.name)
    ));
}

function parentOptionLabel(parent) {
    const id = parentId(parent);
    const rank = Number(parent?.rank || 0);
    const sparks = lineageRollup(parent)
        .filter((entry) => ['Blue', 'Red'].includes(entry.group))
        .slice(0, 3)
        .map((entry) => `${entry.name} ★${entry.stars}`)
        .join(' · ');
    return [
        labelFor(parent, `Veteran #${id}`),
        `Veteran #${id}`,
        rank ? `Rank ${rank}` : '',
        sparks || 'No sparks',
    ].filter(Boolean).join(' · ');
}

function selectedParent(select) {
    const id = Number(select?.value || 0);
    return (state.bootstrap?.parents || []).find((row) => parentId(row) === id) || null;
}

function renderKeyValues(values, className) {
    const rows = Object.entries(values || {}).filter(([, value]) => (
        ['string', 'number'].includes(typeof value) && String(value) !== ''
    ));
    return rows.length ? rows.map(([key, value]) => `
        <span class="${className}"><small>${escapeHtml(key.replaceAll('_', ' '))}</small><strong>${escapeHtml(value)}</strong></span>
    `).join('') : '<span class="muted">Unavailable</span>';
}

function renderLineageFactor(factor) {
    const group = sparkGroup(factor).toLowerCase();
    const stars = Math.max(0, Number(factor?.stars || 0));
    return `<span class="lineage-factor is-${group}">
        <span class="lineage-factor-name">${escapeHtml(factor?.name || 'Unknown')}</span>
        <b>${'★'.repeat(stars) || '—'}</b>
    </span>`;
}

function renderLineageColumns(parent) {
    return lineageNodes(parent).map(({role, node}) => {
        const factors = [...(node.factors || [])].sort((left, right) => (
            SPARK_GROUP_ORDER[sparkGroup(left)] - SPARK_GROUP_ORDER[sparkGroup(right)]
            || Number(right?.stars || 0) - Number(left?.stars || 0)
        ));
        const known = Number(node.card_id || 0) > 0 || factors.length > 0;
        return `<section class="lineage-node">
            <header>
                <span class="lineage-role">${escapeHtml(role)}</span>
                <strong>${escapeHtml(node.name || (known ? 'Unknown' : 'No data'))}</strong>
            </header>
            <div class="lineage-factors">${factors.length
                ? factors.map(renderLineageFactor).join('')
                : '<span class="muted">No sparks recorded.</span>'}</div>
        </section>`;
    }).join('');
}

function renderParentPreview(select, container) {
    const parent = selectedParent(select);
    if (!parent) {
        container.innerHTML = '<p class="empty-state">Select a veteran to inspect stats and sparks.</p>';
        return;
    }
    const rollup = lineageRollup(parent);
    const rollupChips = rollup.map((entry) => `
        <span class="rollup-chip is-${entry.group.toLowerCase()}">${escapeHtml(entry.name)} <b>★${entry.stars}</b></span>
    `).join('');
    const rankScore = Number(parent.rank_score || 0);
    container.innerHTML = `
        <header class="parent-preview-header">
            <div><strong>${escapeHtml(labelFor(parent, `Veteran #${parentId(parent)}`))}</strong><small>Veteran #${parentId(parent)}${rankScore ? ` · Score ${rankScore}` : ''}</small></div>
            <span class="state-badge">Rank ${escapeHtml(parent.rank || '—')}</span>
        </header>
        <div class="parent-metrics">${renderKeyValues(parent.stats, 'parent-metric')}</div>
        <div class="parent-aptitudes">${renderKeyValues(parent.aptitudes, 'aptitude-chip')}</div>
        <section class="lineage-rollup">
            <h4>Inheritance total <span>parent + gp1 + gp2</span></h4>
            <div class="rollup-list">${rollupChips || '<span class="muted">No sparks recorded.</span>'}</div>
        </section>
        <div class="lineage-columns">${renderLineageColumns(parent)}</div>
    `;
}

function selectedDeck() {
    const id = Number(els.deck?.value || 0);
    return (state.bootstrap?.decks || []).find((row) => deckId(row) === id) || null;
}

function selectedDeckSupportIds() {
    const deck = selectedDeck();
    if (!deck) throw new Error('Choose a saved deck.');
    const ids = (deck.cards || []).map((card) => Number(card?.id || card?.support_card_id || 0));
    if (ids.length !== 5 || ids.some((id) => !Number.isInteger(id) || id <= 0) || new Set(ids).size !== 5) {
        throw new Error('Selected deck must contain exactly five distinct owned support cards.');
    }
    return ids;
}

function renderDeckPreview() {
    const deck = selectedDeck();
    if (!deck) {
        els.deckPreview.innerHTML = '<p class="empty-state">Select a saved deck to inspect its five owned support cards.</p>';
        return;
    }
    const cards = Array.isArray(deck.cards) ? deck.cards : [];
    els.deckPreview.innerHTML = `
        <header class="deck-preview-header"><strong>${escapeHtml(deck.name || `Deck ${deckId(deck)}`)}</strong><small>Deck ${deckId(deck)} · ${cards.length}/5 cards</small></header>
        <div class="support-card-list">${cards.map((card, index) => `
            <article class="support-card-row">
                <span class="support-slot">${index + 1}</span>
                <div><strong>${escapeHtml(card.name || `Support #${card.id}`)}</strong><small>${escapeHtml(card.type || 'Unknown')} · ${escapeHtml(card.rarity || '?')}★</small></div>
                <span class="support-lb">LB ${escapeHtml(card.limit_break_count ?? 0)}</span>
            </article>
        `).join('') || '<p class="empty-state">This saved deck has no cards.</p>'}</div>
    `;
}

function selectedFriendSupport() {
    const index = Number(els.friend?.value ?? -1);
    return Number.isInteger(index) && index >= 0
        ? (state.privateFriends[index] || null)
        : null;
}

function friendSupportName(friend) {
    return String(
        friend?.support_name
        || friend?.name
        || friend?.card_name
        || `Support #${friend?.support_card_id || '—'}`,
    );
}

function renderFriendPreview() {
    const friend = selectedFriendSupport();
    els.friendPreview.innerHTML = friend ? `
        <span class="friend-kicker">Friend support</span>
        <strong>${escapeHtml(friendSupportName(friend))}</strong>
        <small>${escapeHtml(friend.type || '')}${friend.limit_break_count !== undefined ? ` · LB ${escapeHtml(friend.limit_break_count)}` : ''}</small>
    ` : '<p class="empty-state">Select a friend support for this setup.</p>';
}

function normalizedSkillIds(value) {
    if (!Array.isArray(value)) return [];
    return [...new Set(value.map(Number).filter((id) => Number.isInteger(id) && id > 0))];
}

function skillById(skillId) {
    return state.skills.find((skill) => Number(skill.id) === Number(skillId)) || null;
}

const SKILL_FACETS = [
    {key: 'style', label: 'Style', options: [[101, 'Front'], [102, 'Pace'], [103, 'Late'], [104, 'End']]},
    {key: 'distance', label: 'Dist', options: [[201, 'Short'], [202, 'Mile'], [203, 'Medium'], [204, 'Long']]},
    {key: 'surface', label: 'Surf', options: [['turf', 'Turf'], ['dirt', 'Dirt']]},
    {key: 'color', label: 'Type', options: [['green', 'Green'], ['blue', 'Blue'], ['yellow', 'Yellow'], ['red', 'Red']]},
];

const SKILL_COLOR_PREFIXES = {
    green: ['1001', '1002', '1003', '1004', '1005', '1006'],
    blue: ['2002'],
    yellow: ['2001', '2004', '2005', '2006', '2009'],
    red: ['3001', '3002', '3004', '3005', '3007'],
};

function skillColorFamily(skill) {
    const iconId = String(skill?.icon_id || '');
    const entry = Object.entries(SKILL_COLOR_PREFIXES).find(
        ([, prefixes]) => prefixes.some((prefix) => iconId.startsWith(prefix)),
    );
    return entry ? entry[0] : '';
}

function skillMatchesFilters(skill, filters) {
    const tags = skill.tags || [];
    if (filters.style && !tags.includes(filters.style)) return false;
    if (filters.distance && !tags.includes(filters.distance)) return false;
    if (filters.surface === 'dirt' && !tags.includes(502)) return false;
    if (filters.surface === 'turf' && tags.includes(502)) return false;
    if (filters.color && skillColorFamily(skill) !== filters.color) return false;
    return true;
}

function skillFacetBadges(skill) {
    const tags = skill.tags || [];
    const labels = [];
    SKILL_FACETS.forEach((facet) => {
        facet.options.forEach(([value, label]) => {
            if (typeof value === 'number' && tags.includes(value)) labels.push(label);
        });
    });
    if (tags.includes(502)) labels.push('Dirt');
    return labels;
}

function renderSkillFilterBar(filtersElement, filters, shownCount, matchCount) {
    const countLabel = shownCount < matchCount
        ? `${shownCount} of ${matchCount} shown`
        : `${matchCount} skill${matchCount === 1 ? '' : 's'}`;
    filtersElement.innerHTML = SKILL_FACETS.map((facet) => `
        <div class="skill-filter-group">
            <span class="skill-filter-facet-label">${escapeHtml(facet.label)}</span>
            ${facet.options.map(([value, label]) => `
                <button type="button"
                    class="skill-filter-chip${filters[facet.key] === value ? ' is-on' : ''}"
                    data-facet="${escapeHtml(facet.key)}" data-value="${escapeHtml(value)}"
                    aria-pressed="${filters[facet.key] === value}">${escapeHtml(label)}</button>
            `).join('')}
        </div>
    `).join('') + `<span class="skill-filter-count">${escapeHtml(countLabel)}</span>`;
}

function renderSkillPicker(picker) {
    const normalized = normalizedSkillIds(state[picker.stateKey]);
    const filters = state.skillFilters[picker.stateKey];
    const query = String(picker.search?.value || '').trim().toLowerCase();
    picker.selection.innerHTML = normalized.length
        ? normalized.map((skillId, index) => {
            const skill = skillById(skillId);
            const name = skill?.name || `Skill #${skillId}`;
            return `<span class="selected-skill-chip">
                <span class="skill-priority">${index + 1}</span>
                <strong>${escapeHtml(name)}</strong>
                <button type="button" data-remove-skill="${skillId}" aria-label="Remove ${escapeHtml(name)}">&times;</button>
            </span>`;
        }).join('')
        : `<span class="muted">${escapeHtml(picker.emptyText)}</span>`;

    const selected = new Set(normalized);
    const filtering = query || Object.values(filters).some((value) => value !== null);
    const matches = state.skills
        .filter((skill) => !selected.has(Number(skill.id)))
        .filter((skill) => !query || String(skill.name || '').toLowerCase().includes(query))
        .filter((skill) => skillMatchesFilters(skill, filters));
    const shown = Math.min(matches.length, filtering ? 80 : 12);
    renderSkillFilterBar(picker.filters, filters, shown, matches.length);
    const overflow = matches.length - shown;
    picker.results.innerHTML = (matches.length
        ? matches.slice(0, shown).map((skill) => {
            const badges = skillFacetBadges(skill);
            const color = skillColorFamily(skill);
            return `
            <button class="skill-result" type="button" data-add-skill="${Number(skill.id)}">
                <strong>${color ? `<i class="skill-color-dot is-${color}" aria-hidden="true"></i>` : ''}${escapeHtml(skill.name || `Skill #${skill.id}`)}</strong>
                <small>${escapeHtml([...badges, skill.rarity ? `Rarity ${skill.rarity}` : ''].filter(Boolean).join(' · ') || `Skill #${skill.id}`)}</small>
            </button>
        `;
        }).join('')
        : '<span class="muted">No matching skills. Clear a filter or search differently.</span>')
        + (overflow > 0
            ? `<span class="muted skill-overflow-note">+${overflow} more — narrow the search or filters.</span>`
            : '');
}

const SKILL_PICKERS = [
    {
        stateKey: 'prioritySkillIds',
        search: els.prioritySkillSearch,
        filters: els.prioritySkillFilters,
        selection: els.prioritySkillSelection,
        results: els.prioritySkillResults,
        emptyText: 'No training priorities selected.',
    },
    {
        stateKey: 'finalSkillIds',
        search: els.finalSkillSearch,
        filters: els.finalSkillFilters,
        selection: els.finalSkillSelection,
        results: els.finalSkillResults,
        emptyText: 'No final purchase priorities selected.',
    },
];

function renderSkillPickers() {
    SKILL_PICKERS.forEach(renderSkillPicker);
}

function normalizedRaceIds(value) {
    if (!Array.isArray(value)) return [];
    return [...new Set(value.map(Number).filter((id) => Number.isInteger(id) && id > 0))];
}

function raceKeys(race) {
    return normalizedRaceIds([race?.id, ...(race?.legacy_ids || [])]);
}

function raceSelected(race) {
    return raceKeys(race).some((id) => state.selectedRaceIds.includes(id));
}

function raceForId(raceId) {
    return state.raceData.find((race) => raceKeys(race).includes(Number(raceId))) || null;
}

function raceYear(race) {
    const match = String(race?.date || '').match(/^(Junior|Classic|Senior) Year/);
    if (match) return {Junior: 1, Classic: 2, Senior: 3}[match[1]];
    const idYear = Math.floor(Number(race?.id || 0) / 100000);
    return [1, 2, 3].includes(idYear) ? idYear : 0;
}

function raceSlotKey(race) {
    return `${raceYear(race)}:${String(race?.date || '').replace(/^(Junior|Classic|Senior) Year /, '')}`;
}

function objectiveRaceSelected(race) {
    return raceKeys(race).some((id) => state.objectiveRaceIds.includes(id));
}

async function loadTraineeObjectiveRaces(cardId) {
    state.objectiveRequestController?.abort();
    const controller = new AbortController();
    const generation = ++state.objectiveRequestGeneration;
    state.objectiveRequestController = controller;
    state.selectedRaceIds = state.selectedRaceIds.filter(
        (id) => !state.objectiveRaceIds.includes(id),
    );
    state.objectiveRaceIds = [];
    renderRacePlanner();
    if (!Number(cardId)) return;

    try {
        const data = await apiJson(
            `/api/independent-training/trainees/${encodeURIComponent(cardId)}/objective-races`,
            {signal: controller.signal},
        );
        if (generation !== state.objectiveRequestGeneration) return;
        const races = (data.objective_races || []).flatMap((objective) => {
            const race = state.raceData.find((candidate) => (
                Number(candidate?.turn) === Number(objective?.turn)
                && Number(candidate?.program_id) === Number(objective?.program_id)
            ));
            return race ? [race] : [];
        });
        const objectiveSlots = new Set(races.map(raceSlotKey));
        state.selectedRaceIds = state.selectedRaceIds.filter((id) => {
            const race = raceForId(id);
            return !race || !objectiveSlots.has(raceSlotKey(race));
        });
        state.objectiveRaceIds = normalizedRaceIds(races.map((race) => race.id));
        state.selectedRaceIds = normalizedRaceIds([
            ...state.selectedRaceIds,
            ...state.objectiveRaceIds,
        ]);
        renderRacePlanner();
    } catch (error) {
        if (error.name !== 'AbortError') {
            showMessage(error.message || 'Unable to load trainee objectives.', 'error');
        }
    }
}

function selectedRaceArray() {
    const seen = new Set();
    return state.selectedRaceIds.flatMap((raceId) => {
        const race = raceForId(raceId);
        const year = raceYear(race);
        const programId = Number(race?.program_id || 0);
        const key = `${year}:${programId}`;
        if (!year || !programId || seen.has(key)) return [];
        seen.add(key);
        return [{year, program_id: programId}];
    });
}

function getRaceSlots(yearIndex) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const periods = ['Early', 'Late'];
    const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
    return months.flatMap((month) => periods.map((period) => {
        const label = `${period} ${month}`;
        const datePrefix = `${yearLabels[yearIndex]} ${label}`;
        return {
            period: label,
            races: state.raceData.filter((race) => String(race.date || '').includes(datePrefix)),
        };
    }));
}

function closeRacePopup() {
    els.racePopup.style.display = 'none';
}

function openRaceSlot(slot, yearIndex) {
    const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
    els.racePopupTitle.textContent = `${yearLabels[yearIndex]} - ${slot.period}`;
    if (!slot.races.length) {
        els.racePopupBody.innerHTML = '<div class="race-slot-popup-empty">No races available</div>';
    } else {
        const slotIds = slot.races.flatMap(raceKeys);
        const slotLocked = slot.races.some(objectiveRaceSelected);
        els.racePopupBody.innerHTML = `<div class="race-slot-popup-list">${slot.races.map((race) => {
            const selected = raceSelected(race);
            const objective = objectiveRaceSelected(race);
            return `<button class="race-slot-popup-item${selected ? ' on' : ''}" type="button" data-race-id="${Number(race.id)}"${slotLocked ? ' disabled' : ''}>
                <div class="race-slot-popup-img"><img src="/races/${encodeURIComponent(race.name)}.png" alt="" onerror="this.style.display='none'"></div>
                <div class="race-slot-popup-info">
                    <div class="race-slot-popup-name-row"><span class="race-slot-popup-grade badge-${escapeHtml(String(race.type || '').toLowerCase().replace('-', ''))}">${escapeHtml(race.type || 'Race')}</span><span class="race-slot-popup-name">${escapeHtml(race.name)}</span></div>
                    <div class="race-slot-popup-meta"><span>${escapeHtml(race.terrain || '')}</span><span>${escapeHtml(race.distance || '')}</span><span>${escapeHtml(race.venue || '')}</span></div>
                </div>
                <span class="race-slot-popup-check">${objective ? 'OBJECTIVE' : (selected ? 'SELECTED' : 'OPTIONAL')}</span>
            </button>`;
        }).join('')}</div>`;
        els.racePopupBody.querySelectorAll('[data-race-id]').forEach((button) => {
            button.addEventListener('click', () => {
                const race = raceForId(Number(button.dataset.raceId));
                if (!race) return;
                const raceIds = raceKeys(race);
                if (raceSelected(race)) {
                    state.selectedRaceIds = state.selectedRaceIds.filter((id) => !raceIds.includes(id));
                } else {
                    const allowMultiple = Number(byId('scenario-select').value) === 4;
                    if (!allowMultiple) {
                        state.selectedRaceIds = state.selectedRaceIds.filter((id) => !slotIds.includes(id));
                    }
                    state.selectedRaceIds.push(Number(race.id));
                }
                state.selectedRaceIds = normalizedRaceIds(state.selectedRaceIds);
                renderRacePlanner();
                openRaceSlot(slot, yearIndex);
            });
        });
    }
    els.racePopup.style.display = 'flex';
}

function renderRacePlanner() {
    const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
    els.raceOptions.innerHTML = '';
    yearLabels.forEach((label, yearIndex) => {
        const block = document.createElement('div');
        block.className = 'race-year-block';
        block.innerHTML = `<div class="race-year-title">${label}</div>`;
        const grid = document.createElement('div');
        grid.className = 'race-time-grid';
        getRaceSlots(yearIndex).forEach((slot) => {
            const cell = document.createElement('button');
            cell.className = 'race-time-cell';
            cell.type = 'button';
            const selected = slot.races.find(raceSelected);
            const objective = selected && objectiveRaceSelected(selected);
            cell.innerHTML = `<div class="race-time-label">${slot.period}</div>${selected ? `
                <div class="race-cell-selected-img"><img src="/races/${encodeURIComponent(selected.name)}.png" alt="" onerror="this.style.display='none'"><span class="race-cell-selected-grade badge-${escapeHtml(String(selected.type || '').toLowerCase().replace('-', ''))}">${escapeHtml(selected.type || '')}</span></div>
                <div class="race-cell-selected-name">${escapeHtml(selected.name)}</div>
                <div class="race-cell-selected-mode">${objective ? 'OBJECTIVE' : 'OPTIONAL'}</div>
            ` : '<div class="race-time-plus">+</div>'}`;
            cell.addEventListener('click', () => openRaceSlot(slot, yearIndex));
            grid.appendChild(cell);
        });
        block.appendChild(grid);
        els.raceOptions.appendChild(block);
    });
    const count = selectedRaceArray().length;
    els.raceCount.textContent = `${count} race${count === 1 ? '' : 's'}`;
}

function raceIdsFromAgenda(agenda) {
    const directIds = normalizedRaceIds([...(agenda?.races || []), ...(agenda?.mandatory_races || [])]);
    return normalizedRaceIds([
        ...directIds,
        ...raceIdsFromEntries(agenda?.race_array || []),
    ]).map((id) => Number(raceForId(id)?.id || id));
}

function raceIdsFromEntries(entries) {
    return (entries || []).flatMap((entry) => {
        const race = state.raceData.find((candidate) => (
            raceYear(candidate) === Number(entry?.year)
            && Number(candidate?.program_id) === Number(entry?.program_id)
        ));
        return race ? [Number(race.id)] : [];
    });
}

function populateRaceSchedules() {
    const agendas = state.bootstrap?.saved_race_agendas || [];
    els.raceSchedule.innerHTML = '<option value="">Start empty</option>' + agendas.map((agenda, index) => (
        `<option value="${index}">${escapeHtml(agenda.name || `Schedule ${index + 1}`)}</option>`
    )).join('');
}

function renderSelectionPreviews() {
    renderParentPreview(els.parentOne, els.parentOnePreview);
    renderParentPreview(els.parentTwo, els.parentTwoPreview);
    renderDeckPreview();
    renderFriendPreview();
}

function populateChoices() {
    const bootstrap = state.bootstrap || {};
    els.trainee.innerHTML = '<option value="">Select trainee</option>'
        + (bootstrap.trainees || []).map((row) => {
            const id = traineeId(row);
            return `<option value="${id}">${escapeHtml(labelFor(row, `Trainee #${id}`))}</option>`;
        }).join('');

    const parentOptions = (bootstrap.parents || []).map((row) => {
        const id = parentId(row);
        return `<option value="${id}">${escapeHtml(parentOptionLabel(row))}</option>`;
    }).join('');
    els.parentOne.innerHTML = '<option value="">Select parent</option>' + parentOptions;
    els.parentTwo.innerHTML = '<option value="">Select parent</option>' + parentOptions;

    els.deck.innerHTML = '<option value="">Select saved deck</option>'
        + (bootstrap.decks || []).map((deck) => {
            const cards = (deck.cards || []).map((card) => card.name || `#${card.id}`).join(' / ');
            return `<option value="${deckId(deck)}">${escapeHtml(deck.name || `Deck ${deckId(deck)}`)}${cards ? ` · ${escapeHtml(cards)}` : ''}</option>`;
        }).join('');
    const firstDeck = (bootstrap.decks || [])[0];
    if (firstDeck) els.deck.value = String(deckId(firstDeck));
    renderSelectionPreviews();
}

function populateIndependentPresets() {
    const selectedName = els.preset.value;
    els.preset.innerHTML = '<option value="">Select a saved setup</option>'
        + state.presets.map((preset) => (
            `<option value="${escapeHtml(preset.name)}">${escapeHtml(preset.name)}</option>`
        )).join('');
    if (state.presets.some((preset) => preset.name === selectedName)) {
        els.preset.value = selectedName;
    }
}

function setSelectValue(element, value) {
    const text = String(value ?? '');
    if (Array.from(element.options).some((option) => option.value === text)) {
        element.value = text;
        return true;
    }
    return false;
}

async function applyIndependentPreset(preset) {
    const setup = preset?.setup || {};
    setSelectValue(els.trainee, setup.card_id);
    setSelectValue(els.parentOne, setup.parent_id_1);
    setSelectValue(els.parentTwo, setup.parent_id_2);
    setSelectValue(byId('scenario-select'), setup.scenario_id);
    setSelectValue(byId('running-style'), setup.running_style);
    setSelectValue(els.deck, setup.deck_id);
    byId('training-policy-ground-type').value = setup.training_policy_ground_type || 1;
    setSelectValue(
        byId('training-policy-rate-set-id'),
        setup.training_policy_param_rate_set_id,
    );
    byId('run-count').value = preset.count || 1;
    setSelectValue(byId('tp-mode'), preset.tp_mode || 'wait');
    state.prioritySkillIds = normalizedSkillIds(
        [...(setup.priority_skill_array || [])]
            .sort((left, right) => Number(left.priority) - Number(right.priority))
            .map((entry) => entry.skill_id),
    );
    state.finalSkillIds = normalizedSkillIds(setup.final_skill_ids);
    state.factorTargets = Array.isArray(setup.factor_reroll?.targets)
        ? setup.factor_reroll.targets
        : [];
    els.reroll.checked = Boolean(setup.factor_reroll?.enabled);
    els.raceSchedule.value = '';
    await loadTraineeObjectiveRaces(Number(els.trainee.value));
    state.selectedRaceIds = normalizedRaceIds([
        ...state.selectedRaceIds,
        ...raceIdsFromEntries(setup.race_array || []),
    ]);
    const friendIndex = Number.isInteger(preset?.friend_index)
        ? preset.friend_index
        : -1;
    if (friendIndex >= 0
        && friendIndex < state.privateFriends.length) {
        els.friend.value = String(friendIndex);
    } else {
        els.friend.value = '';
        showMessage('Saved friend support is unavailable; choose a current friend support.', 'error');
    }
    renderFactorTargets();
    renderSkillPickers();
    renderRacePlanner();
    renderSelectionPreviews();
}

function persistConvenience() {
    const values = {
        trainee: els.trainee.value,
        parentOne: els.parentOne.value,
        parentTwo: els.parentTwo.value,
        scenario: byId('scenario-select').value,
        runningStyle: byId('running-style').value,
        deck: els.deck.value,
        groundType: byId('training-policy-ground-type').value,
        rateSet: byId('training-policy-rate-set-id').value,
        prioritySkillIds: [...state.prioritySkillIds],
        finalSkillIds: [...state.finalSkillIds],
        selectedRaceIds: [...state.selectedRaceIds],
        reroll: els.reroll.checked,
        targets: state.factorTargets,
        runCount: byId('run-count').value,
        tpMode: byId('tp-mode').value,
    };
    localStorage.setItem('sweepy_independent_setup', JSON.stringify(values));
}

function restoreConvenience() {
    let saved = {};
    try {
        saved = JSON.parse(localStorage.getItem('sweepy_independent_setup') || '{}');
    } catch (error) {
        saved = {};
    }
    const mapping = {
        trainee: els.trainee,
        parentOne: els.parentOne,
        parentTwo: els.parentTwo,
        scenario: byId('scenario-select'),
        runningStyle: byId('running-style'),
        deck: els.deck,
        groundType: byId('training-policy-ground-type'),
        rateSet: byId('training-policy-rate-set-id'),
        runCount: byId('run-count'),
        tpMode: byId('tp-mode'),
    };
    Object.entries(mapping).forEach(([key, element]) => {
        if (saved[key] === undefined || !element) return;
        if (element.tagName === 'SELECT') {
            const exists = Array.from(element.options).some(
                (option) => option.value === String(saved[key]),
            );
            if (!exists) return;
        }
        element.value = saved[key];
    });
    els.reroll.checked = Boolean(saved.reroll);
    state.factorTargets = Array.isArray(saved.targets) ? saved.targets : [];
    state.prioritySkillIds = normalizedSkillIds(saved.prioritySkillIds);
    state.finalSkillIds = normalizedSkillIds(saved.finalSkillIds);
    state.selectedRaceIds = normalizedRaceIds(saved.selectedRaceIds);
    renderFactorTargets();
    renderSkillPickers();
    renderRacePlanner();
}

async function hydratePrivateSelection() {
    try {
        const response = await fetch('/api/session');
        const session = await response.json();
        const friends = Array.isArray(session?.friends) ? session.friends : [];
        state.privateFriends = friends.filter((friend) => (
            Number(friend?.viewer_id) > 0 && Number(friend?.support_card_id) > 0
        ));
        els.friend.innerHTML = '<option value="">Select friend support</option>'
            + state.privateFriends.map((friend, index) => (
                `<option value="${index}">${escapeHtml(friendSupportName(friend))}${friend.limit_break_count !== undefined ? ` · LB ${escapeHtml(friend.limit_break_count)}` : ''}</option>`
            )).join('');

        const selected = session?.selection?.friend;
        const selectedIndex = state.privateFriends.findIndex((friend) => (
            Number(friend.viewer_id) === Number(selected?.viewer_id)
            && Number(friend.support_card_id) === Number(selected?.support_card_id)
        ));
        if (selectedIndex >= 0) els.friend.value = String(selectedIndex);
        else if (state.privateFriends.length === 1) els.friend.value = '0';
        renderFriendPreview();
    } catch (error) {
        state.privateFriends = [];
        els.friend.innerHTML = '<option value="">Open Dashboard and refresh friend supports</option>';
        renderFriendPreview();
    }
}

function renderFactorTargets() {
    els.targets.hidden = !els.reroll.checked;
    byId('add-factor-target').hidden = !els.reroll.checked;
    els.targets.innerHTML = state.factorTargets.length
        ? state.factorTargets.map((target, index) => `
            <div class="factor-target-row" data-target-index="${index}">
                <label>Kind
                    <select class="form-input" data-target-field="category">
                        <option value="pink"${target.category === 'pink' ? ' selected' : ''}>Aptitude / Pink</option>
                        <option value="blue"${target.category === 'blue' ? ' selected' : ''}>Stat / Blue</option>
                    </select>
                </label>
                <label>Name<input class="form-input" data-target-field="name" value="${escapeHtml(target.name || '')}" placeholder="Dirt"></label>
                <label>Minimum stars<input class="form-input" data-target-field="minimum_stars" type="number" min="1" max="3" value="${Number(target.minimum_stars || 2)}"></label>
                <button class="btn btn-sm btn-danger" data-remove-target="${index}" type="button">Remove</button>
            </div>
        `).join('')
        : '<p class="empty-state">Add a Blue or Pink spark target.</p>';
}

function buildSetup() {
    const supports = selectedDeckSupportIds();
    const friend = selectedFriendSupport();
    if (!friend) throw new Error('Choose a friend support from the current Dashboard session.');
    const parentOne = asPositiveInt(els.parentOne.value, 'Parent 1');
    const parentTwo = asPositiveInt(els.parentTwo.value, 'Parent 2');
    if (parentOne === parentTwo) throw new Error('Choose two different parents.');

    const targets = els.reroll.checked
        ? state.factorTargets.map((target) => ({
            category: target.category,
            name: String(target.name || '').trim(),
            minimum_stars: Number(target.minimum_stars || 0),
        }))
        : [];
    if (els.reroll.checked && (!targets.length || targets.some((target) => !target.name))) {
        throw new Error('Enabled factor reroll needs at least one named target.');
    }

    return {
        card_id: asPositiveInt(els.trainee.value, 'Trainee'),
        support_card_ids: supports,
        friend_viewer_id: asPositiveInt(friend.viewer_id, 'Friend viewer ID'),
        friend_card_id: asPositiveInt(friend.support_card_id, 'Friend support ID'),
        parent_id_1: parentOne,
        parent_id_2: parentTwo,
        rental_viewer_id: 0,
        rental_trained_chara_id: 0,
        scenario_id: asPositiveInt(byId('scenario-select').value, 'Scenario'),
        deck_id: asPositiveInt(els.deck.value, 'Deck'),
        running_style: asPositiveInt(byId('running-style').value, 'Running style'),
        training_policy_ground_type: asPositiveInt(
            byId('training-policy-ground-type').value,
            'Training policy ground type',
        ),
        training_policy_param_rate_set_id: asPositiveInt(
            byId('training-policy-rate-set-id').value,
            'Training policy rate set',
        ),
        priority_skill_array: state.prioritySkillIds.map((skillId, index) => ({
            priority: index + 1,
            skill_id: skillId,
        })),
        final_skill_ids: [...state.finalSkillIds],
        race_array: selectedRaceArray(),
        factor_reroll: {enabled: els.reroll.checked, targets},
    };
}

function stateClass(value) {
    return String(value || 'UNKNOWN').toLowerCase().replaceAll('_', '-');
}

function formatDuration(milliseconds) {
    const totalSeconds = Math.max(0, Math.ceil(milliseconds / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds]
        .map((value) => String(value).padStart(2, '0'))
        .join(':');
}

function runTitle(run) {
    const setup = run?.setup_summary || {};
    const trainee = (state.bootstrap?.trainees || []).find(
        (row) => traineeId(row) === Number(setup.card_id),
    );
    return labelFor(trainee, `Trainee #${setup.card_id || '—'}`);
}

function renderStatus() {
    const status = state.status || {};
    const runner = status.runner || {};
    const runs = Array.isArray(status.runs) ? status.runs : [];
    const activeStates = new Set(['STARTING', 'RUNNING', 'COLLECTING', 'FINALIZING', 'NEEDS_ATTENTION']);
    const active = runs.find((run) => activeStates.has(run.state));
    const queued = runs.filter((run) => !['COMPLETED', 'CANCELLED', 'FAILED'].includes(run.state));
    const completed = runs.filter((run) => run.state === 'COMPLETED').slice(-10).reverse();

    els.account.textContent = status.account || state.bootstrap?.account_label || 'No bound account';
    els.executor.textContent = runner.state || 'IDLE';
    els.executor.className = `state-badge is-${stateClass(runner.state)}`;
    const detectedTpCost = Number(
        runner.detected_tp_cost || state.bootstrap?.detected_tp_cost || 0,
    );
    const tpCostSource = String(
        runner.tp_cost_source || state.bootstrap?.tp_cost_source || '',
    );
    const tpCostError = String(
        runner.tp_cost_error || state.bootstrap?.tp_cost_error || '',
    );
    els.detectedTpCost.textContent = detectedTpCost > 0
        ? `${detectedTpCost} TP${tpCostSource ? ` · ${tpCostSource}` : ''}`
        : (tpCostError ? `Unavailable · ${tpCostError}` : 'Unavailable');
    els.detectedTpCost.title = tpCostError;

    if (!active) {
        const orphan = status.untracked_server_run;
        const orphanBlock = orphan ? `
            <div class="active-actions">
                <button class="btn btn-sm" id="adopt-server-run" type="button">Collect Server Run</button>
                <small>The game reports a career Sweepy is not tracking (trainee ${escapeHtml(orphan.card_id)}, scenario ${escapeHtml(orphan.scenario_id)}${orphan.collectable ? ', already finished' : ', still running'}). It occupies the only career slot, so every queued run fails to start with API error 102. Collecting it ends the career and picks a factor without any reroll targets.</small>
            </div>
        ` : '';
        els.active.innerHTML = `<p class="empty-state">No active run. Executor: ${escapeHtml(runner.state || 'IDLE')}.</p>${orphanBlock}`;
    } else {
        const end = Number(active.server_end_time || 0) * 1000;
        const remaining = end ? Math.max(0, end - Date.now()) : 0;
        const timeLabel = end && remaining > 0 ? formatDuration(remaining) : 'Checking server';
        const discardable = active.state === 'NEEDS_ATTENTION';
        els.active.innerHTML = `
            <article class="active-summary">
                <div><span>Run</span><strong>${escapeHtml(runTitle(active))}</strong><small>${escapeHtml(active.run_id)}</small></div>
                <div><span>State</span><strong class="run-state is-${stateClass(active.state)}">${escapeHtml(active.state)}</strong></div>
                <div><span>Server ETA</span><strong>${escapeHtml(timeLabel)}</strong><small>Countdown is display-only</small></div>
                <div><span>Next action</span><strong>${escapeHtml(active.next_action || 'Automatic')}</strong><small>${escapeHtml(active.error || '')}</small></div>
            </article>
            ${discardable ? `
            <div class="active-actions">
                <button class="btn btn-sm btn-danger" data-discard-run="${escapeHtml(active.run_id)}" type="button">Remove Run</button>
                <small>Reconcile keeps failing? Remove Run will reconcile/finish the server career first when it has already started. The queue only continues after the server slot is clear.</small>
            </div>
            ` : ''}
        `;
    }

    els.queue.innerHTML = queued.length ? queued.map((run) => `
        <article class="queue-card">
            <div class="queue-position">#${escapeHtml(run.position)}</div>
            <div>
                <strong>${escapeHtml(runTitle(run))}</strong>
                <small>${escapeHtml(run.run_id)}</small>
            </div>
            <span class="run-state is-${stateClass(run.state)}">${escapeHtml(run.state)}</span>
            ${run.state === 'QUEUED' ? `<button class="btn btn-sm btn-danger" data-cancel-run="${escapeHtml(run.run_id)}" type="button">Remove</button>` : ''}
            ${run.state === 'NEEDS_ATTENTION' ? `<button class="btn btn-sm btn-danger" data-discard-run="${escapeHtml(run.run_id)}" type="button">Remove</button>` : ''}
        </article>
    `).join('') : '<p class="empty-state">Queue is empty.</p>';

    els.results.innerHTML = completed.length ? completed.map((run) => {
        const result = run.result || {};
        const veteranId = result.trained_chara_id || result.veteran?.trained_chara_id || '—';
        const lottery = result.selected_lottery_id || run.selected_lottery_id || '—';
        return `
            <article class="result-card">
                <div><strong>${escapeHtml(runTitle(run))}</strong><small>Veteran #${escapeHtml(veteranId)}</small></div>
                <div><span>Factor choice</span><strong>#${escapeHtml(lottery)}</strong></div>
                <div><span>Completed</span><strong>${escapeHtml(new Date(Number(run.updated_at || 0) * 1000).toLocaleString())}</strong></div>
            </article>
        `;
    }).join('') : '<p class="empty-state">No completed runs yet.</p>';

    const stopped = Boolean(status.control?.stop_after_current);
    byId('stop-after-current').disabled = stopped;
    byId('resume-queue').disabled = !stopped;
}

async function refreshStatus() {
    if (state.pollBusy) return;
    state.pollBusy = true;
    try {
        state.status = await apiJson("/api/independent-training/status");
        renderStatus();
    } catch (error) {
        // apiJson already rendered the error.
    } finally {
        state.pollBusy = false;
    }
}

async function command(url, successMessage) {
    try {
        await apiJson(url, {method: 'POST'});
        showMessage(successMessage, 'success');
        await refreshStatus();
    } catch (error) {
        // apiJson already rendered the error.
    }
}

async function bootstrap() {
    const [bootstrapData, skillData, raceData] = await Promise.all([
        apiJson('/api/independent-training/bootstrap'),
        apiJson("/api/skills"),
        apiJson('/assets/data/uma_race_data.json'),
    ]);
    state.bootstrap = bootstrapData;
    state.status = state.bootstrap.status || null;
    state.presets = Array.isArray(state.bootstrap.presets)
        ? state.bootstrap.presets
        : [];
    state.skills = Object.entries(skillData.skills || {}).map(([id, skill]) => ({
        id: Number(id),
        ...skill,
    })).filter((skill) => Number.isInteger(skill.id) && skill.id > 0 && skill.name)
        .sort((left, right) => String(left.name).localeCompare(String(right.name)));
    state.raceData = Array.isArray(raceData.races) ? raceData.races : [];
    populateChoices();
    populateIndependentPresets();
    populateRaceSchedules();
    restoreConvenience();
    await hydratePrivateSelection();
    renderSelectionPreviews();
    renderSkillPickers();
    renderRacePlanner();
    renderStatus();
}

[els.parentOne, els.parentTwo, els.deck, els.friend].forEach((element) => {
    element.addEventListener('change', renderSelectionPreviews);
});

function bindSkillPicker(picker) {
    picker.search.addEventListener('input', renderSkillPickers);
    picker.filters.addEventListener('click', (event) => {
        const chip = event.target.closest('[data-facet]');
        if (!chip) return;
        const facet = chip.dataset.facet;
        const raw = chip.dataset.value;
        const value = ['style', 'distance'].includes(facet) ? Number(raw) : raw;
        const filters = state.skillFilters[picker.stateKey];
        filters[facet] = filters[facet] === value ? null : value;
        renderSkillPickers();
        picker.filters.querySelector(
            `[data-facet="${facet}"][data-value="${raw}"]`,
        )?.focus();
    });
    picker.results.addEventListener('click', (event) => {
        const button = event.target.closest('[data-add-skill]');
        if (!button) return;
        state[picker.stateKey] = normalizedSkillIds([
            ...state[picker.stateKey],
            Number(button.dataset.addSkill),
        ]);
        renderSkillPickers();
        picker.search.focus();
    });
    picker.selection.addEventListener('click', (event) => {
        const button = event.target.closest('[data-remove-skill]');
        if (!button) return;
        const skillId = Number(button.dataset.removeSkill);
        state[picker.stateKey] = state[picker.stateKey].filter((id) => id !== skillId);
        renderSkillPickers();
        picker.search.focus();
    });
}

SKILL_PICKERS.forEach(bindSkillPicker);

els.savePreset.addEventListener('click', async () => {
    try {
        const name = els.presetName.value.trim();
        if (!name) throw new Error('Enter a preset name.');
        const preset = await apiJson("/api/independent-training/presets", {
            method: 'POST',
            body: JSON.stringify({
                name,
                setup: buildSetup(),
                count: asPositiveInt(byId('run-count').value, 'Repeat count'),
                tp_mode: byId('tp-mode').value,
            }),
        });
        state.presets = [
            ...state.presets.filter((row) => row.name !== preset.name),
            preset,
        ];
        populateIndependentPresets();
        els.preset.value = preset.name;
        els.presetName.value = preset.name;
        showMessage(`Saved preset “${preset.name}”.`, 'success');
    } catch (error) {
        showMessage(error.message || 'Unable to save preset.', 'error');
    }
});

els.loadPreset.addEventListener('click', async () => {
    const name = els.preset.value;
    if (!name) {
        showMessage('Choose a saved setup to load.', 'error');
        return;
    }
    try {
        const preset = await apiJson(
            `/api/independent-training/presets/${encodeURIComponent(name)}`,
        );
        await applyIndependentPreset(preset);
        els.presetName.value = preset.name;
        showMessage(`Loaded preset “${preset.name}”.`, 'success');
    } catch (error) {
        showMessage(error.message || 'Unable to load preset.', 'error');
    }
});

els.deletePreset.addEventListener('click', async () => {
    const name = els.preset.value || els.presetName.value.trim();
    if (!name) {
        showMessage('Choose a saved setup to delete.', 'error');
        return;
    }
    try {
        await apiJson(
            `/api/independent-training/presets/${encodeURIComponent(name)}`,
            {method: 'DELETE'},
        );
        state.presets = state.presets.filter((preset) => preset.name !== name);
        populateIndependentPresets();
        els.presetName.value = '';
        showMessage(`Deleted preset “${name}”.`, 'success');
    } catch (error) {
        showMessage(error.message || 'Unable to delete preset.', 'error');
    }
});

els.preset.addEventListener('change', () => {
    els.presetName.value = els.preset.value;
});

els.trainee.addEventListener('change', () => {
    loadTraineeObjectiveRaces(Number(els.trainee.value));
});
els.raceSchedule.addEventListener('change', () => {
    const agendaIds = els.raceSchedule.value === ''
        ? []
        : raceIdsFromAgenda(
            state.bootstrap?.saved_race_agendas?.[Number(els.raceSchedule.value)],
        );
    const objectiveSlots = new Set(
        state.objectiveRaceIds.map((id) => raceSlotKey(raceForId(id))),
    );
    state.selectedRaceIds = normalizedRaceIds([
        ...agendaIds.filter((id) => {
            const race = raceForId(id);
            return !race || !objectiveSlots.has(raceSlotKey(race));
        }),
        ...state.objectiveRaceIds,
    ]);
    renderRacePlanner();
});
byId('independent-race-popup-close').addEventListener('click', closeRacePopup);
els.racePopup.addEventListener('click', (event) => {
    if (event.target === els.racePopup) closeRacePopup();
});

els.form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
        const payload = {
            setup: buildSetup(),
            count: asPositiveInt(byId('run-count').value, 'Repeat count'),
            tp_mode: byId('tp-mode').value,
        };
        await apiJson("/api/independent-training/runs", {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        persistConvenience();
        showMessage(`Added ${payload.count} immutable run${payload.count === 1 ? '' : 's'}.`, 'success');
        await refreshStatus();
    } catch (error) {
        showMessage(error.message || 'Unable to add runs.', 'error');
    }
});

els.reroll.addEventListener('change', () => {
    if (els.reroll.checked && !state.factorTargets.length) {
        state.factorTargets.push({category: 'pink', name: 'dirt', minimum_stars: 2});
    }
    renderFactorTargets();
});

byId('add-factor-target').addEventListener('click', () => {
    state.factorTargets.push({category: 'pink', name: '', minimum_stars: 2});
    renderFactorTargets();
});

els.targets.addEventListener('input', (event) => {
    const row = event.target.closest('[data-target-index]');
    const field = event.target.dataset.targetField;
    if (!row || !field) return;
    const index = Number(row.dataset.targetIndex);
    state.factorTargets[index][field] = field === 'minimum_stars'
        ? Number(event.target.value)
        : event.target.value;
});

els.targets.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-target]');
    if (!button) return;
    state.factorTargets.splice(Number(button.dataset.removeTarget), 1);
    renderFactorTargets();
});

async function discardRun(runId) {
    const confirmed = window.confirm(
        'Remove this run from Sweepy? If it already started, Sweepy will '
        + 'reconcile/finish the server career first. The queue will not continue '
        + 'until the server slot is clear.',
    );
    if (!confirmed) return;
    await apiJson(`/api/independent-training/runs/${encodeURIComponent(runId)}/discard`, {
        method: 'POST',
    });
    showMessage('Run cleanup accepted.', 'success');
    await refreshStatus();
}

els.queue.addEventListener('click', async (event) => {
    const discard = event.target.closest('[data-discard-run]');
    if (discard) {
        await discardRun(discard.dataset.discardRun);
        return;
    }
    const button = event.target.closest('[data-cancel-run]');
    if (!button) return;
    await apiJson(`/api/independent-training/runs/${encodeURIComponent(button.dataset.cancelRun)}`, {
        method: 'DELETE',
    });
    showMessage('Queued run removed.', 'success');
    await refreshStatus();
});

els.active.addEventListener('click', async (event) => {
    if (event.target.closest('#adopt-server-run')) {
        await apiJson("/api/independent-training/adopt-server-run", { method: 'POST' });
        showMessage('Collecting the untracked server career.', 'success');
        await refreshStatus();
        return;
    }
    const button = event.target.closest('[data-discard-run]');
    if (!button) return;
    await discardRun(button.dataset.discardRun);
});

byId('start-queue').addEventListener('click', () => command(
    "/api/independent-training/start",
    'Queue executor accepted.',
));
byId('stop-after-current').addEventListener('click', () => command(
    "/api/independent-training/stop-after-current",
    'Queue will stop after the active run.',
));
byId('resume-queue').addEventListener('click', () => command(
    "/api/independent-training/resume",
    'Queue resumed.',
));
byId('reconcile-queue').addEventListener('click', () => command(
    "/api/independent-training/reconcile",
    'Reconciliation requested.',
));

bootstrap().catch(() => {});
setInterval(refreshStatus, 5000);
