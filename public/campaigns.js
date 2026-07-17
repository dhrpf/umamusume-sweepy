'use strict';

const state = {
    campaigns: [],
    selectedCampaign: null,
    recommendations: [],
    loopRecommendations: { loops: [], ideal_upgrades: [] },
    friendSupports: [],
    raceById: new Map(),
    session: null,
    presets: [],
    draft: {
        finalUmaCardId: 0,
        sparkTargets: [],
        selectedFinalParent: null,
        selectedLoop: null,
        pinnedCharaIds: [],
        deckAssignments: {},
        friendAssignments: {},
        options: {
            allowRental: false,
            autoUseBestVeteran: false,
            stopWhenTargetReached: false,
            presetName: '',
            maximumRuns: 30,
            maximumRuntimeHours: 24,
        },
    },
};
let campaignAccount = '';
let parentRequestSequence = 0;
let loopRequestSequence = 0;
let parentController = null;
let loopController = null;
let campaignLoadSequence = 0;
let campaignLoadController = null;
let requestedCampaignId = '';
let campaignPollBusy = false;
const pendingMutations = new Set();

const byId = (id) => document.getElementById(id);
const els = {
    message: byId('campaign-message'), list: byId('campaign-list'), account: byId('campaign-account'),
    create: byId('campaign-create-view'), detail: byId('campaign-detail'), finalUma: byId('final-uma-select'),
    targets: byId('spark-targets'), parents: byId('parent-recommendations'), loops: byId('loop-recommendations'),
    upgrades: byId('loop-upgrades'), decks: byId('deck-assignments'), preset: byId('base-preset-select'),
    preview: byId('campaign-preview'), maximumRuns: byId('maximum-runs'), runtime: byId('maximum-runtime-hours'),
    allowRental: byId('allow-rental'), autoVeteran: byId('auto-use-best-veteran'),
    stopWhenTargetReached: byId('stop-when-target-reached'),
    refreshFriends: byId('refresh-friend-supports-btn'),
};

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
}

function showMessage(message = '', kind = '') {
    els.message.textContent = message;
    els.message.className = `campaign-message${kind ? ` is-${kind}` : ''}`;
}

async function apiJson(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: options.body ? { 'Content-Type': 'application/json', ...(options.headers || {}) } : options.headers,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.success === false) throw new Error(data.detail || `Request failed (${response.status})`);
        return data;
    } catch (error) {
        if (error.name === 'AbortError') throw error;
        showMessage(error.message || 'Request failed', 'error');
        throw error;
    }
}

function labelFor(row, fallback = 'Unknown') {
    if (!row || typeof row !== 'object') return fallback;
    return String(row.name || row.chara_name || row.card_name || row.card_id || row.id || row.chara_id || fallback);
}

function numberFrom(row, keys) {
    for (const key of keys) {
        const value = Number(row?.[key]);
        if (Number.isFinite(value) && value > 0) return value;
    }
    return 0;
}

function accountName() {
    const session = state.session || {};
    const account = session.account;
    return String(campaignAccount || session.account_name || session.accountName || (typeof account === 'object' && (account.name || account.account)) || (typeof account === 'string' && account) || '').trim();
}

function accountValue(value) {
    return String(typeof value === 'object' && value ? value.name || value.account || '' : value || '').trim();
}

function clearLoopSelection() {
    loopRequestSequence += 1;
    loopController?.abort();
    state.loopRecommendations = { loops: [], ideal_upgrades: [] };
    state.draft.selectedLoop = null;
    state.draft.pinnedCharaIds = [];
    state.draft.deckAssignments = {};
    state.draft.friendAssignments = {};
}

function clearParentAndLoop() {
    parentRequestSequence += 1;
    parentController?.abort();
    state.recommendations = [];
    state.draft.selectedFinalParent = null;
    clearLoopSelection();
}

async function withPending(key, button, operation) {
    if (pendingMutations.has(key)) return;
    pendingMutations.add(key);
    const relatedButtons = key === 'recommend-loop'
        ? [byId('recommend-loop-btn'), byId('recompute-loop-btn')]
        : key.startsWith('action:') ? [...document.querySelectorAll('[data-campaign-action], [data-candidate-id]')] : [button];
    relatedButtons.filter(Boolean).forEach((item) => { item.disabled = true; });
    try { return await operation(); }
    finally {
        pendingMutations.delete(key);
        relatedButtons.filter((item) => item?.isConnected).forEach((item) => { item.disabled = false; });
    }
}

function presetName(row) {
    return String(row?.name || row?.preset_name || '').trim();
}

function resetDraft() {
    const savedPreset = localStorage.getItem('uma_selected_preset') || '';
    const defaultPreset = state.presets.some((preset) => presetName(preset) === savedPreset) ? savedPreset : presetName(state.presets[0]);
    state.recommendations = [];
    state.loopRecommendations = { loops: [], ideal_upgrades: [] };
    state.draft = {
        finalUmaCardId: 0, sparkTargets: [], selectedFinalParent: null, selectedLoop: null,
        pinnedCharaIds: [], deckAssignments: {}, friendAssignments: {},
        options: { allowRental: false, autoUseBestVeteran: false, stopWhenTargetReached: false, presetName: defaultPreset, maximumRuns: 30, maximumRuntimeHours: 24 },
    };
    syncInputs();
    renderBuilder();
}

function syncInputs() {
    els.finalUma.value = state.draft.finalUmaCardId || '';
    els.preset.value = state.draft.options.presetName;
    els.maximumRuns.value = state.draft.options.maximumRuns;
    els.runtime.value = state.draft.options.maximumRuntimeHours;
    els.allowRental.checked = state.draft.options.allowRental;
    els.autoVeteran.checked = state.draft.options.autoUseBestVeteran;
    els.stopWhenTargetReached.checked = state.draft.options.stopWhenTargetReached;
}

function renderBootstrapChoices() {
    const umas = Array.isArray(state.session?.umas) ? state.session.umas : [];
    els.finalUma.innerHTML = '<option value="">Select Final Uma</option>' + umas.map((uma) => {
        const id = numberFrom(uma, ['card_id', 'id']);
        return `<option value="${id}">${escapeHtml(labelFor(uma))}</option>`;
    }).join('');
    els.preset.innerHTML = '<option value="">Select preset</option>' + state.presets.map((preset) => {
        const name = presetName(preset);
        return `<option value="${escapeHtml(name)}">${escapeHtml(name || 'Unnamed preset')}</option>`;
    }).join('');
}

function renderCampaignList() {
    els.account.textContent = accountName() ? `Account: ${accountName()}` : 'No active account metadata';
    if (!state.campaigns.length) {
        els.list.innerHTML = '<p class="empty-state">No campaigns yet.</p>';
        return;
    }
    els.list.innerHTML = state.campaigns.map((campaign) => {
        const id = campaign.id || campaign.campaign_id;
        const active = (state.selectedCampaign?.id || state.selectedCampaign?.campaign_id) === id;
        return `<button class="campaign-list-item${active ? ' is-selected' : ''}" type="button" data-campaign-id="${escapeHtml(id)}">
            <strong>${escapeHtml(campaign.name || campaign.spec?.strategy?.preset_name || `Campaign ${id}`)}</strong>
            <span>${escapeHtml(campaign.state || campaign.status || 'UNKNOWN')}</span>
        </button>`;
    }).join('');
}

function addTarget(category) {
    clearParentAndLoop();
    state.draft.sparkTargets.push({ category, name: '', minimum_stars: 1, priority: 'required' });
    renderBuilder();
}

function renderTargets() {
    els.targets.innerHTML = state.draft.sparkTargets.length ? state.draft.sparkTargets.map((target, index) => `
        <div class="target-row" data-target-index="${index}">
            <span class="target-kind">${escapeHtml(target.category)}</span>
            <label>Name<input class="form-input" data-field="name" value="${escapeHtml(target.name)}" required></label>
            <label>Min stars<input class="form-input" data-field="minimum_stars" type="number" min="1" max="9" value="${target.minimum_stars}"></label>
            <label>Priority<select class="form-input" data-field="priority"><option value="required"${target.priority === 'required' ? ' selected' : ''}>Required</option><option value="preferred"${target.priority === 'preferred' ? ' selected' : ''}>Preferred</option></select></label>
            <button class="btn btn-sm btn-danger-soft" data-remove-target="${index}" type="button" aria-label="Remove ${escapeHtml(target.category)} target">Remove</button>
        </div>`).join('') : '<p class="empty-state">Add at least one required Blue or Pink target.</p>';
}

function parentTrainedId(row) {
    return numberFrom(row?.veteran || row, ['trained_chara_id', 'instance_id']);
}

function renderParents() {
    els.parents.innerHTML = state.recommendations.length ? state.recommendations.slice(0, 3).map((row, index) => {
        const selected = state.draft.selectedFinalParent === row;
        return `<article class="recommendation-card${selected ? ' is-selected' : ''}">
            <p class="rank">#${index + 1}</p><h4>${escapeHtml(labelFor(row.veteran || row, `Chara ${row.chara_id}`))}</h4>
            <p>Score ${escapeHtml(row.score ?? '—')} · Affinity ${escapeHtml(row.best_affinity ?? row.pairing?.affinity ?? '—')}</p>
            <p>Required ${escapeHtml(row.required_progress ?? '—')} · Preferred ${escapeHtml(row.preferred_progress ?? '—')}</p>
            <button class="btn btn-sm${selected ? ' btn-primary' : ''}" data-parent-index="${index}" type="button">${selected ? 'Selected' : 'Choose'}</button>
        </article>`;
    }).join('') : '<p class="empty-state">No parent recommendations loaded.</p>';
}

function loopIds(loop) {
    const ids = loop?.chara_ids || loop?.base_chara_ids || loop?.members?.map((row) => row.chara_id || row.base_chara_id);
    return (ids || []).map(Number).filter((id) => id > 0);
}

function baseCharaId(value) {
    const id = Number(value);
    if (!Number.isFinite(id) || id <= 0) return 0;
    return id >= 100000 ? Math.floor(id / 100) : id;
}

function loopMembers(loop) {
    const sourceMembers = Array.isArray(loop?.members) ? loop.members : [];
    const sessionUmas = Array.isArray(state.session?.umas) ? state.session.umas : [];
    return loopIds(loop).map((charaId) => {
        const member = sourceMembers.find((row) => {
            const directId = numberFrom(row, ['base_chara_id', 'chara_id']);
            return directId === charaId || baseCharaId(numberFrom(row, ['card_id', 'id'])) === charaId;
        });
        const sessionUma = sessionUmas.find((row) => baseCharaId(numberFrom(row, ['card_id', 'id'])) === charaId);
        const name = String(member?.name || member?.chara_name || sessionUma?.name || sessionUma?.chara_name || `Chara ${charaId}`);
        return { charaId, name, member };
    });
}

function renderLoopCards(rows, upgrade = false) {
    if (!rows.length) return '<p class="empty-state">None available.</p>';
    return rows.map((loop, index) => {
        const members = loopMembers(loop);
        const selected = !upgrade && state.draft.selectedLoop === loop;
        return `<article class="recommendation-card${selected ? ' is-selected' : ''}">
            <p class="rank">#${index + 1}</p><h4>${members.map((member) => escapeHtml(member.name)).join(' · ') || 'Unknown loop'}</h4>
            <p>Score ${escapeHtml(loop.score ?? '—')} · Shared G1 ${escapeHtml(loop.shared_g1_count ?? loop.score_breakdown?.shared_g1 ?? '—')}</p>
            ${upgrade ? `<span class="badge">Non-runnable upgrade suggestion</span><button class="btn btn-sm" data-copy-upgrade-index="${index}" type="button">Pin owned matching members</button>` : `<div class="pin-grid">${members.map((member) => `<button class="btn btn-sm${state.draft.pinnedCharaIds.includes(member.charaId) ? ' btn-primary' : ''}" data-pin-id="${member.charaId}" type="button">${state.draft.pinnedCharaIds.includes(member.charaId) ? 'Unpin' : 'Pin'} ${escapeHtml(member.name)}</button>`).join('')}</div><button class="btn btn-sm${selected ? ' btn-primary' : ''}" data-loop-index="${index}" type="button">${selected ? 'Selected' : 'Choose runnable loop'}</button>`}
        </article>`;
    }).join('');
}

function renderLoops() {
    els.loops.innerHTML = renderLoopCards(state.loopRecommendations.loops || []);
    els.upgrades.innerHTML = renderLoopCards(state.loopRecommendations.ideal_upgrades || [], true);
}

function availableDecks() {
    return (Array.isArray(state.session?.decks) ? state.session.decks : []).map((deck) => ({ ...deck, id: numberFrom(deck, ['deck_id', 'id']), name: labelFor(deck, `Deck ${numberFrom(deck, ['deck_id', 'id'])}`) })).filter((deck) => deck.id >= 1 && deck.id <= 10);
}

function friendKey(friend) {
    const viewerId = numberFrom(friend, ['viewer_id', 'friend_viewer_id']);
    const supportCardId = numberFrom(friend, ['support_card_id', 'friend_card_id']);
    return viewerId && supportCardId ? `${viewerId}:${supportCardId}` : '';
}

function friendLabel(friend) {
    const supportName = String(friend?.support_name || `Support ${numberFrom(friend, ['support_card_id'])}`);
    const ownerName = String(friend?.name || 'Unknown owner');
    const limitBreak = Number(friend?.limit_break_count);
    return `${supportName} · ${ownerName}${Number.isFinite(limitBreak) ? ` · LB${limitBreak}` : ''}`;
}

function deckSupportIds(deckId) {
    const deck = availableDecks().find((row) => row.id === Number(deckId));
    const cards = Array.isArray(deck?.cards) ? deck.cards : [];
    return new Set(cards.map((card) => numberFrom(card, ['id', 'support_card_id'])).filter((id) => id > 0));
}

function friendConflictsWithDeck(friend, deckId) {
    const supportCardId = numberFrom(friend, ['support_card_id', 'friend_card_id']);
    return supportCardId > 0 && deckSupportIds(deckId).has(supportCardId);
}

function renderDecks() {
    const members = loopMembers(state.draft.selectedLoop);
    if (members.length !== 4) {
        els.decks.innerHTML = '<p class="empty-state">Choose a runnable four-member loop first.</p>';
        return;
    }
    const decks = availableDecks();
    const friends = state.friendSupports.filter((friend) => friendKey(friend));
    els.decks.innerHTML = members.map((member) => {
        const deckId = Number(state.draft.deckAssignments[member.charaId]);
        const selectedFriend = state.draft.friendAssignments[member.charaId];
        const selectedFriendKey = friendKey(selectedFriend);
        const friendOptions = friends.map((friend) => {
            const key = friendKey(friend);
            const conflict = friendConflictsWithDeck(friend, deckId);
            return `<option value="${escapeHtml(key)}"${selectedFriendKey === key ? ' selected' : ''}${conflict ? ' disabled' : ''}>${escapeHtml(friendLabel(friend))}${conflict ? ' (already in deck)' : ''}</option>`;
        }).join('');
        return `<div class="deck-row"><strong>${escapeHtml(member.name)}</strong><select class="form-input" data-deck-chara="${member.charaId}" aria-label="Deck for ${escapeHtml(member.name)}"><option value="">Select deck</option>${decks.map((deck) => `<option value="${deck.id}"${deckId === deck.id ? ' selected' : ''}>${escapeHtml(deck.name)} (ID ${deck.id})</option>`).join('')}</select><select class="form-input" data-friend-chara="${member.charaId}" aria-label="Friend support for ${escapeHtml(member.name)}"><option value="">${friends.length ? 'Select friend support' : 'Load friend supports first'}</option>${friendOptions}</select></div>`;
    }).join('');
}

function recommendationContext() {
    if (!state.draft.finalUmaCardId) throw new Error('Select Final Uma first.');
    const targets = state.draft.sparkTargets.map((target) => ({ ...target, name: target.name.trim().toLowerCase(), minimum_stars: Number(target.minimum_stars) }));
    if (!targets.length || targets.some((target) => !target.name || target.minimum_stars < 1 || target.minimum_stars > 9)) throw new Error('Complete every spark target.');
    if (!targets.some((target) => target.priority === 'required')) throw new Error('At least one Required target is required.');
    return { final_uma_card_id: state.draft.finalUmaCardId, spark_targets: targets, limit: 3 };
}

function buildSpec() {
    const context = recommendationContext();
    if (!state.draft.selectedFinalParent) throw new Error('Choose a final parent recommendation.');
    const selectedMembers = loopMembers(state.draft.selectedLoop);
    if (selectedMembers.length !== 4) throw new Error('Choose a runnable four-member loop.');
    const loopMembersSpec = selectedMembers.map((member) => {
        const deckId = Number(state.draft.deckAssignments[member.charaId]);
        if (deckId < 1 || deckId > 10) throw new Error(`Assign a deck to ${member.name}.`);
        const friend = state.draft.friendAssignments[member.charaId];
        if (!friendKey(friend)) throw new Error(`Assign a friend support to ${member.name}.`);
        if (friendConflictsWithDeck(friend, deckId)) throw new Error(`Friend support for ${member.name} is already present in the selected deck.`);
        return {
            chara_id: member.charaId,
            deck_id: deckId,
            pinned: state.draft.pinnedCharaIds.includes(member.charaId),
            friend_support: {
                viewer_id: numberFrom(friend, ['viewer_id', 'friend_viewer_id']),
                support_card_id: numberFrom(friend, ['support_card_id', 'friend_card_id']),
                support_name: String(friend.support_name || ''),
            },
        };
    });
    const account = accountName();
    if (!account) throw new Error('Backend session exposes no usable campaign account name.');
    if (!state.draft.options.presetName) throw new Error('Select a persisted base preset.');
    const agenda = state.draft.selectedLoop?.shared_g1_agenda || {};
    const raceIds = (rows) => [...new Set((Array.isArray(rows) ? rows : []).map((row) => numberFrom(row, ['program_id', 'id'])).filter((id) => id > 0))];
    return {
        account, spec_version: 2,
        goal: { purpose: 'parent', target_factors: [] },
        strategy: {
            preset_name: state.draft.options.presetName,
            maximum_runs: Number(state.draft.options.maximumRuns),
            maximum_runtime_hours: Number(state.draft.options.maximumRuntimeHours),
            tp_mode: 'wait', approval_mode: 'ambiguity_only',
            stop_when_target_reached: state.draft.options.stopWhenTargetReached,
        },
        final_uma: { card_id: context.final_uma_card_id },
        spark_targets: context.spark_targets,
        final_parent: { chara_id: Number(state.draft.selectedFinalParent.chara_id), trained_chara_id: parentTrainedId(state.draft.selectedFinalParent) },
        loop_members: loopMembersSpec,
        race_plan: { core: raceIds(agenda.agenda), optional: raceIds(agenda.optional), deferable: raceIds(agenda.skipped) },
        options: { allow_rental: state.draft.options.allowRental, auto_use_best_veteran: state.draft.options.autoUseBestVeteran },
    };
}

function renderPreview() {
    try { els.preview.textContent = JSON.stringify(buildSpec(), null, 2); }
    catch (error) { els.preview.textContent = `Incomplete: ${error.message}`; }
}

function renderBuilder() {
    renderTargets(); renderParents(); renderLoops(); renderDecks(); renderPreview();
}

function progressBar(label, value) {
    const numeric = Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 100);
    return `<div class="progress-row"><span>${escapeHtml(label)}</span><div class="progress-track" role="progressbar" aria-label="${escapeHtml(label)} progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${numeric}"><div class="progress-fill" style="width:${numeric}%"></div></div><strong>${numeric}%</strong></div>`;
}

function safeJson(value) {
    return value && (Array.isArray(value) ? value.length : Object.keys(value).length) ? `<pre class="detail-json">${escapeHtml(JSON.stringify(value, null, 2))}</pre>` : '<p class="empty-state">No data.</p>';
}

function candidateId(candidate) {
    return String(candidate?.candidate_id || candidate?.id || '');
}

function campaignCandidates(campaign) {
    const rows = [
        ...(Array.isArray(campaign?.candidates) ? campaign.candidates : []),
        ...(Array.isArray(campaign?.context?.candidates) ? campaign.context.candidates : []),
    ];
    return rows.filter((candidate, index) => {
        const id = candidateId(candidate);
        return id && rows.findIndex((row) => candidateId(row) === id) === index;
    });
}

function resolveUmaIdentity(cardId) {
    const normalizedCardId = Number(cardId) || 0;
    const umas = Array.isArray(state.session?.umas) ? state.session.umas : [];
    const exact = umas.find((uma) => numberFrom(uma, ['card_id', 'id']) === normalizedCardId);
    const baseId = baseCharaId(normalizedCardId);
    const fallback = exact || umas.find((uma) => baseCharaId(numberFrom(uma, ['card_id', 'id'])) === baseId);
    return {
        name: fallback ? labelFor(fallback, `Uma #${normalizedCardId || '—'}`) : `Uma #${normalizedCardId || '—'}`,
        cardId: normalizedCardId,
    };
}

function resolveParentIdentity(campaign, finalParent) {
    const trainedCharaId = Number(finalParent?.trained_chara_id) || 0;
    const charaId = Number(finalParent?.chara_id) || 0;
    const parents = Array.isArray(state.session?.parents) ? state.session.parents : [];
    const parent = parents.find((row) => numberFrom(row, ['trained_chara_id', 'instance_id', 'id']) === trainedCharaId);
    const candidate = campaignCandidates(campaign).find((row) => Number(row?.trained_chara_id) === trainedCharaId);
    const umas = Array.isArray(state.session?.umas) ? state.session.umas : [];
    const uma = umas.find((row) => baseCharaId(numberFrom(row, ['card_id', 'id'])) === charaId);
    const source = parent || candidate || uma;
    return {
        name: source ? labelFor(source, `Uma #${charaId || trainedCharaId || '—'}`) : `Uma #${charaId || trainedCharaId || '—'}`,
        charaId,
        trainedCharaId,
        cardId: numberFrom(parent || candidate || uma, ['card_id', 'id']),
    };
}

function selectedCandidate(campaign) {
    const candidates = campaignCandidates(campaign);
    const selectedId = String(campaign?.selected_candidate_id || '');
    return candidates.find((candidate) => candidateId(candidate) === selectedId)
        || candidates.find((candidate) => candidate?.selected)
        || null;
}

function challengerCandidate(campaign) {
    const review = campaign?.context?.pending_review || {};
    const embedded = review.candidate && typeof review.candidate === 'object' ? review.candidate : null;
    const id = candidateId(embedded) || String(review.candidate_id || '');
    const stored = campaignCandidates(campaign).find((candidate) => candidateId(candidate) === id);
    if (stored) return stored;
    if (embedded) return embedded;
    return id ? { candidate_id: id, evaluation: review.evaluation || {} } : null;
}

function candidateEvaluation(candidate) {
    return candidate?.evaluation && typeof candidate.evaluation === 'object' ? candidate.evaluation : {};
}

function candidateMetric(candidate, key) {
    const value = Number(candidateEvaluation(candidate)[key]);
    return Number.isFinite(value) ? value : 0;
}

function percentText(value) {
    return `${Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 1000) / 10}%`;
}

function signedValue(value, suffix = '') {
    const numeric = Number(value) || 0;
    const rounded = Math.round(numeric * 10) / 10;
    return `${rounded > 0 ? '+' : ''}${rounded}${suffix}`;
}

function finalSetupStatus(candidate) {
    return String(candidateEvaluation(candidate).final_setup?.status || (candidate?.accepted ? 'READY' : 'IN_PROGRESS'));
}

function normalizedFactorCategory(value) {
    const category = String(value || '').trim().toLowerCase().replaceAll('_', '-');
    return ({
        stat: 'blue', blue: 'blue',
        aptitude: 'pink', pink: 'pink',
        unique: 'green', green: 'green',
        skill: 'white-skill', 'white-skill': 'white-skill',
        race: 'white-race', 'white-race': 'white-race',
    })[category] || 'other';
}

function nodeFactors(node) {
    if (!node || typeof node !== 'object') return [];
    if (Array.isArray(node.factors)) return node.factors.map((factor) => ({ ...factor }));
    const buckets = [
        ['blue', 'stat'], ['pink', 'aptitude'], ['green', 'unique'],
        ['white_skill', 'skill'], ['white-skill', 'skill'],
        ['white_race', 'race'], ['white-race', 'race'], ['other', 'other'],
    ];
    return buckets.flatMap(([key, category]) => (Array.isArray(node[key]) ? node[key] : []).map((factor) => ({ ...factor, category: factor.category || category })));
}

function factorChip(factor) {
    const category = normalizedFactorCategory(factor?.category);
    const name = factor?.name || `Factor ${factor?.factor_id || '—'}`;
    const stars = Math.max(0, Number(factor?.stars) || 0);
    return `<span class="spark-chip is-${category}" title="Factor ${escapeHtml(factor?.factor_id || 'unknown')}">${escapeHtml(name)} <strong>${escapeHtml(stars)}★</strong></span>`;
}

function groupedFactorRows(factors) {
    const labels = {
        blue: 'Blue', pink: 'Pink', green: 'Green',
        'white-race': 'White Race', 'white-skill': 'White Skill', other: 'Other',
    };
    const order = ['blue', 'pink', 'green', 'white-race', 'white-skill', 'other'];
    const grouped = new Map(order.map((category) => [category, []]));
    for (const factor of factors) grouped.get(normalizedFactorCategory(factor?.category)).push(factor);
    return order.filter((category) => grouped.get(category).length).map((category) => `
        <div class="spark-group"><span class="spark-group-label">${labels[category]}</span><div class="spark-chip-list">${grouped.get(category).map(factorChip).join('')}</div></div>`).join('');
}

function renderTargetSparks(candidate) {
    const rows = candidateEvaluation(candidate).targets?.rows;
    if (!Array.isArray(rows) || !rows.length) return '<p class="empty-state">No target spark evaluation.</p>';
    return `<div class="target-spark-list">${rows.map((row) => {
        const actual = Math.max(0, Number(row.actual_stars) || 0);
        const minimum = Math.max(0, Number(row.minimum_stars) || 0);
        const matched = row.matched === true || actual >= minimum;
        return `<div class="target-spark-row"><div><span class="spark-chip is-${escapeHtml(normalizedFactorCategory(row.category))}">${escapeHtml(row.name || 'Unknown')} <strong>${actual}★</strong></span><span class="target-threshold">Target ${minimum}★ · ${escapeHtml(row.priority || 'required')}</span></div><span class="target-result${matched ? ' is-met' : ' is-missing'}">${matched ? 'Met' : `Missing ${Math.max(0, minimum - actual)}★`}</span></div>`;
    }).join('')}</div>`;
}

function renderOwnSparks(candidate) {
    const tree = candidateEvaluation(candidate).factor_tree;
    const factors = nodeFactors(tree?.self);
    if (!factors.length) return '<p class="empty-state">Spark snapshot unavailable for this historical candidate.</p>';
    return `<div class="spark-groups">${groupedFactorRows(factors)}</div>`;
}

function renderLineageSparks(candidate) {
    const tree = candidateEvaluation(candidate).factor_tree;
    if (!tree || typeof tree !== 'object' || !Object.keys(tree).length) return '';
    const nodeLabels = [
        ['self', 'Self'], ['p1', 'Parent 1'], ['parent1', 'Parent 1'],
        ['p2', 'Parent 2'], ['parent2', 'Parent 2'],
        ['gp1', 'Grandparent 1'], ['grandparent1', 'Grandparent 1'],
        ['gp2', 'Grandparent 2'], ['grandparent2', 'Grandparent 2'],
        ['gp3', 'Grandparent 3'], ['grandparent3', 'Grandparent 3'],
        ['gp4', 'Grandparent 4'], ['grandparent4', 'Grandparent 4'],
    ];
    const seenLabels = new Set();
    const nodes = nodeLabels.flatMap(([key, label]) => {
        if (!tree[key] || seenLabels.has(label)) return [];
        seenLabels.add(label);
        const factors = nodeFactors(tree[key]);
        return factors.length ? [`<article class="lineage-node"><h5>${label}</h5>${groupedFactorRows(factors)}</article>`] : [];
    });
    return nodes.length ? `<details class="lineage-sparks"><summary>View full lineage sparks</summary><div class="lineage-node-grid">${nodes.join('')}</div></details>` : '';
}

function candidateCard(candidate, role, campaign) {
    if (!candidate) return `<article class="candidate-card is-empty"><p class="empty-state">No ${escapeHtml(role)} candidate is available.</p></article>`;
    const id = candidateId(candidate);
    const evaluation = candidateEvaluation(candidate);
    const isSelected = id === String(campaign?.selected_candidate_id || '') || candidate.selected;
    const roleLabel = role === 'current' ? 'Current selected' : 'New challenger';
    const buttonLabel = role === 'current' ? 'Keep selected' : 'Choose challenger';
    return `<article class="candidate-card${isSelected ? ' is-selected' : ''}">
        <div class="candidate-card-header"><span class="badge">${roleLabel}</span><span class="candidate-status">${escapeHtml(finalSetupStatus(candidate))}</span></div>
        <h4>${escapeHtml(labelFor(candidate, id || 'Candidate'))}</h4>
        <p class="candidate-id">${escapeHtml(id || 'Unknown candidate ID')}${isSelected ? ' · Selected' : ''}</p>
        <div class="candidate-metrics">
            <div><span>Required</span><strong>${percentText(evaluation.required_progress)}</strong></div>
            <div><span>Preferred</span><strong>${percentText(evaluation.preferred_progress)}</strong></div>
            <div><span>Affinity</span><strong>${escapeHtml(evaluation.best_affinity ?? '—')}</strong></div>
            <div><span>Score</span><strong>${escapeHtml(Number.isFinite(Number(candidate.score)) ? Math.round(Number(candidate.score) * 100) / 100 : '—')}</strong></div>
        </div>
        <div class="candidate-spark-section"><h5>Target Sparks</h5>${renderTargetSparks(candidate)}</div>
        <div class="candidate-spark-section"><h5>Own Sparks</h5>${renderOwnSparks(candidate)}</div>
        ${renderLineageSparks(candidate)}
        <button class="btn btn-sm btn-primary" data-candidate-id="${escapeHtml(id)}" type="button">${buttonLabel}</button>
    </article>`;
}

function targetRowsByKey(candidate) {
    const rows = candidateEvaluation(candidate).targets?.rows;
    return new Map((Array.isArray(rows) ? rows : []).map((row) => [`${String(row.category || '').toLowerCase()}:${String(row.name || '').toLowerCase()}`, row]));
}

function renderCandidateDelta(current, challenger) {
    if (!current || !challenger) return '<div class="candidate-delta"><strong>VS</strong><p>Comparison unavailable.</p></div>';
    const requiredDelta = (candidateMetric(challenger, 'required_progress') - candidateMetric(current, 'required_progress')) * 100;
    const preferredDelta = (candidateMetric(challenger, 'preferred_progress') - candidateMetric(current, 'preferred_progress')) * 100;
    const affinityDelta = candidateMetric(challenger, 'best_affinity') - candidateMetric(current, 'best_affinity');
    const currentTargets = targetRowsByKey(current);
    const challengerTargets = targetRowsByKey(challenger);
    const targetKeys = [...new Set([...currentTargets.keys(), ...challengerTargets.keys()])];
    const targetDelta = targetKeys.map((key) => {
        const before = currentTargets.get(key);
        const after = challengerTargets.get(key);
        const name = after?.name || before?.name || key;
        const beforeStars = Number(before?.actual_stars) || 0;
        const afterStars = Number(after?.actual_stars) || 0;
        return `<li><span>${escapeHtml(name)}</span><strong>${beforeStars}★ → ${afterStars}★</strong></li>`;
    }).join('');
    return `<div class="candidate-delta"><strong>VS</strong><dl><div><dt>Required</dt><dd>${signedValue(requiredDelta, '%')}</dd></div><div><dt>Preferred</dt><dd>${signedValue(preferredDelta, '%')}</dd></div><div><dt>Affinity</dt><dd>${signedValue(affinityDelta)}</dd></div></dl>${targetDelta ? `<ul>${targetDelta}</ul>` : ''}</div>`;
}

function tradeoffExplanation(current, challenger) {
    if (!current || !challenger) return 'Candidate comparison data is incomplete.';
    const requiredDelta = candidateMetric(challenger, 'required_progress') - candidateMetric(current, 'required_progress');
    const affinityDelta = candidateMetric(challenger, 'best_affinity') - candidateMetric(current, 'best_affinity');
    const missed = (candidateEvaluation(challenger).targets?.rows || []).filter((row) => row.matched === false).map((row) => row.name).filter(Boolean);
    if (requiredDelta < 0) return `Keep the current candidate unless affinity is worth losing required progress${missed.length ? ` for ${missed.join(', ')}` : ''}. The challenger changes affinity by ${signedValue(affinityDelta)}.`;
    if (requiredDelta > 0) return `The challenger improves required progress and changes affinity by ${signedValue(affinityDelta)}.`;
    if (affinityDelta > 0) return `The challenger preserves required progress and gains ${signedValue(affinityDelta)} affinity.`;
    return 'The challenger does not improve required progress or affinity. Review the spark details before replacing the current candidate.';
}

function renderCandidateHistory(campaign, excludedIds) {
    const rows = campaignCandidates(campaign).filter((candidate) => !excludedIds.has(candidateId(candidate)));
    if (!rows.length) return '';
    return `<details class="candidate-history"><summary>Other candidates (${rows.length})</summary><div class="candidate-history-scroll"><table class="candidate-history-table"><thead><tr><th>Candidate</th><th>Required</th><th>Preferred</th><th>Affinity</th><th>Status</th><th>Decision</th><th>Score</th></tr></thead><tbody>${rows.map((candidate) => {
        const evaluation = candidateEvaluation(candidate);
        const id = candidateId(candidate);
        const selected = id === String(campaign.selected_candidate_id || '') || candidate.selected;
        return `<tr${selected ? ' class="is-selected"' : ''}><td><strong>${escapeHtml(labelFor(candidate, id))}</strong><small>${escapeHtml(id)}${selected ? ' · Selected' : ''}</small></td><td>${percentText(evaluation.required_progress)}</td><td>${percentText(evaluation.preferred_progress)}</td><td>${escapeHtml(evaluation.best_affinity ?? '—')}</td><td>${escapeHtml(finalSetupStatus(candidate))}</td><td>${escapeHtml(evaluation.decision || '—')}</td><td>${escapeHtml(Number.isFinite(Number(candidate.score)) ? Math.round(Number(candidate.score) * 100) / 100 : '—')}</td></tr>`;
    }).join('')}</tbody></table></div></details>`;
}

function agendaProgramIds(agenda, group) {
    const aliases = {
        CORE: ['CORE', 'core', 'agenda'],
        OPTIONAL: ['OPTIONAL', 'optional'],
        DEFERABLE: ['DEFERABLE', 'deferable', 'skipped'],
    }[group];
    const raw = aliases.map((key) => agenda?.[key]).find((value) => Array.isArray(value)) || [];
    return [...new Set(raw.map((row) => Number(typeof row === 'object' ? row.program_id || row.id : row)).filter((id) => id > 0))];
}

function renderRaceRow(programId) {
    const race = state.raceById.get(Number(programId)) || {};
    return `<div class="race-row"><div><strong>${escapeHtml(race.name || `Race #${programId}`)}</strong><span>${escapeHtml(race.date || 'Date unavailable')}</span></div><div class="race-meta"><span>${escapeHtml(race.type || '—')}</span><span>${escapeHtml([race.terrain, race.distance].filter(Boolean).join(' · ') || '—')}</span><span>${escapeHtml(race.venue || '—')}</span><small>#${escapeHtml(programId)}</small></div></div>`;
}

function renderRaceAgenda(agenda) {
    const policies = {
        CORE: 'Always prioritized by the campaign race plan.',
        OPTIONAL: 'Attempted when the run is healthy and the schedule allows it.',
        DEFERABLE: 'Skipped first when training, condition, or schedule conflicts occur.',
    };
    return `<div class="race-agenda-grid">${['CORE', 'OPTIONAL', 'DEFERABLE'].map((group) => {
        const ids = agendaProgramIds(agenda, group);
        return `<article class="race-group-card"><div class="race-group-header"><div><h4>${group}</h4><p>${policies[group]}</p></div><span class="badge">${ids.length} race${ids.length === 1 ? '' : 's'}</span></div>${ids.length ? `<details${group === 'CORE' ? ' open' : ''}><summary>Show ${ids.length} planned race${ids.length === 1 ? '' : 's'}</summary><div class="race-list">${ids.map(renderRaceRow).join('')}</div></details>` : '<p class="empty-state">No races configured.</p>'}</article>`;
    }).join('')}</div>`;
}

function hasData(value) {
    return Boolean(value && (Array.isArray(value) ? value.length : typeof value === 'object' ? Object.keys(value).length : true));
}

function optionalDataSection(title, value) {
    return hasData(value) ? `<section><h3>${escapeHtml(title)}</h3>${safeJson(value)}</section>` : '';
}

function detailActions(campaign) {
    const campaignState = String(campaign.state || campaign.status || '').toUpperCase();
    const next = campaign.next_action || '';
    const context = campaign.context || {};
    const preparedAutoRun = Boolean(context.prepared_run && context.review_required === false && !context.run_start);
    const terminal = ['COMPLETED', 'CANCELLED', 'FAILED'].includes(campaignState);
    const actions = [];
    if (['DRAFT', 'READY'].includes(campaignState)) actions.push(['activate', 'Activate']);
    if (!terminal && !['DRAFT', 'PAUSED'].includes(campaignState)) actions.push(['pause', 'Pause']);
    if (campaignState === 'PAUSED') actions.push(['resume', 'Resume']);
    if (['RUNNING_CAREER', 'EVALUATING_RESULT'].includes(campaignState)) {
        actions.push(['advance', campaignState === 'RUNNING_CAREER' ? 'Check Run' : 'Collect Result']);
    }
    if (campaignState === 'SELECTING_LINEAGE' && (next === 'start_career' || preparedAutoRun)) {
        actions.push(['approve-run', 'Start Career']);
    } else if (campaignState === 'SELECTING_LINEAGE' || ['prepare_next_run', 'select_lineage'].includes(next)) {
        actions.push(['prepare-next-run', 'Prepare next run']);
    }
    if (campaignState === 'COMPLETED') actions.push(['continue-preferred', 'Continue preferred']);
    if (!terminal) actions.push(['cancel', 'Cancel']);
    return actions.map(([action, label]) => `<button class="btn btn-sm${action === 'cancel' ? ' btn-danger-soft' : ''}" data-campaign-action="${action}" type="button">${label}</button>`).join('');
}

function renderReview(campaign) {
    const review = campaign.context?.pending_review;
    if (!review || String(campaign.state).toUpperCase() !== 'NEEDS_USER_INPUT') return '';
    if (campaign.next_action === 'select_candidate') {
        const current = selectedCandidate(campaign);
        const challenger = challengerCandidate(campaign);
        const excludedIds = new Set([candidateId(current), candidateId(challenger)].filter(Boolean));
        return `<section class="review-panel"><div class="campaign-heading-row"><div><p class="eyebrow">Decision required</p><h3>Post-run Tradeoff</h3></div><span class="badge">Compare sparks</span></div><p class="tradeoff-explanation">${escapeHtml(tradeoffExplanation(current, challenger))}</p><div class="tradeoff-grid">${candidateCard(current, 'current', campaign)}${renderCandidateDelta(current, challenger)}${candidateCard(challenger, 'challenger', campaign)}</div>${renderCandidateHistory(campaign, excludedIds)}</section>`;
    }
    if (['approve_run', 'prepared_run'].includes(campaign.next_action)) return `<section class="review-panel"><h3>Pre-run Review</h3>${safeJson(review)}<button class="btn btn-primary" data-campaign-action="approve-run" type="button">Approve Run</button></section>`;
    return '';
}

function renderDetail() {
    const campaign = state.selectedCampaign;
    if (!campaign) { els.detail.innerHTML = '<p class="empty-state">Select a campaign.</p>'; return; }
    const spec = campaign.spec || {};
    const context = campaign.context || {};
    const agenda = context.race_agenda || context.shared_g1_agenda || campaign.race_agenda || spec.race_plan || {};
    const selected = selectedCandidate(campaign);
    const finalUma = resolveUmaIdentity(spec.final_uma?.card_id);
    const finalParent = resolveParentIdentity(campaign, spec.final_parent || {});
    const required = context.required_progress ?? campaign.required_progress ?? selected?.evaluation?.required_progress;
    const preferred = context.preferred_progress ?? campaign.preferred_progress ?? selected?.evaluation?.preferred_progress;
    const runs = campaign.usage?.runs ?? campaign.run_count ?? context.run_count ?? 0;
    const rotation = context.rotation || {};
    const runIndex = Number(rotation.run_index ?? context.rotation_index);
    const loopCharaIds = Array.isArray(rotation.loop_chara_ids) ? rotation.loop_chara_ids : Array.isArray(context.loop_chara_ids) ? context.loop_chara_ids : (spec.loop_members || []).map((member) => member.chara_id);
    const derivedNextTrainee = Number.isFinite(runIndex) && loopCharaIds.length ? loopCharaIds[((runIndex % loopCharaIds.length) + loopCharaIds.length) % loopCharaIds.length] : 0;
    const nextTrainee = rotation.next_trainee || context.next_trainee || derivedNextTrainee || '—';
    const lineage = context.lineage || context.resolved_choices || campaign.lineage;
    const projected = context.projected_final_setup || campaign.projected_final_setup;
    els.detail.innerHTML = `
        <div class="status-strip"><span class="badge">${escapeHtml(campaign.state || campaign.status || 'UNKNOWN')}</span><span>Next: ${escapeHtml(campaign.next_action || '—')}</span>${selected ? `<span>Selected: ${escapeHtml(labelFor(selected, candidateId(selected)))}</span>` : ''}</div>
        <div class="detail-grid"><article><h3>Final Setup</h3><div class="setup-identity-list"><div class="setup-identity-row"><span>Final Uma</span><div><strong>${escapeHtml(finalUma.name)}</strong><small class="setup-identity-meta">Card #${escapeHtml(finalUma.cardId || '—')}</small></div></div><div class="setup-identity-row"><span>Final Parent</span><div><strong>${escapeHtml(finalParent.name)}</strong><small class="setup-identity-meta">Chara #${escapeHtml(finalParent.charaId || '—')} · Veteran #${escapeHtml(finalParent.trainedCharaId || '—')}${finalParent.cardId ? ` · Card #${escapeHtml(finalParent.cardId)}` : ''}</small></div></div></div></article><article><h3>Usage</h3><p>Runs: ${escapeHtml(runs)}</p><p>Rotation run: ${escapeHtml(Number.isFinite(runIndex) ? runIndex : '—')} · Next trainee: ${escapeHtml(nextTrainee?.name || nextTrainee?.chara_id || nextTrainee)}</p></article></div>
        <section><h3>Target Progress</h3>${progressBar('Required', required)}${progressBar('Preferred', preferred)}</section>
        ${renderReview(campaign)}
        <section><h3>Actions</h3><div class="inline-actions">${detailActions(campaign)}</div></section>
        ${optionalDataSection('Lineage & Resolved Choices', lineage)}
        ${optionalDataSection('Projected Final Setup', projected)}
        <section><h3>Race Agenda</h3>${renderRaceAgenda(agenda)}</section>
        <details class="debug-panel"><summary>Raw campaign data</summary>${safeJson({ campaign, events: campaign.events || context.recent_events, candidates: campaign.candidates || context.candidates })}</details>`;
}

async function loadCampaign(id) {
    const normalizedId = String(id);
    const sequence = ++campaignLoadSequence;
    requestedCampaignId = normalizedId;
    campaignLoadController?.abort();
    campaignLoadController = new AbortController();
    try {
        const data = await apiJson(`/api/campaigns/${encodeURIComponent(normalizedId)}`, { signal: campaignLoadController.signal });
        if (sequence !== campaignLoadSequence || requestedCampaignId !== normalizedId) return false;
        state.selectedCampaign = { ...(data.campaign || {}) };
        if (Array.isArray(data.events)) state.selectedCampaign.events = data.events;
        if (Array.isArray(data.candidates)) state.selectedCampaign.candidates = data.candidates;
        renderCampaignList(); renderDetail();
        return true;
    } catch (_) {
        return false;
    }
}

async function reloadCampaigns() {
    const data = await apiJson('/api/campaigns');
    state.campaigns = Array.isArray(data.campaigns) ? data.campaigns : [];
    campaignAccount = accountValue(data.account) || campaignAccount;
    renderCampaignList();
}

async function pollCampaignProgress() {
    const campaign = state.selectedCampaign;
    const id = campaign?.id || campaign?.campaign_id;
    const campaignState = String(campaign?.state || campaign?.status || '').toUpperCase();
    if (!id || !['SELECTING_LINEAGE', 'RUNNING_CAREER', 'EVALUATING_RESULT'].includes(campaignState)) return;
    if (campaignPollBusy || pendingMutations.has(`action:${id}`)) return;

    campaignPollBusy = true;
    try {
        await apiJson(`/api/campaigns/${encodeURIComponent(id)}/advance`, { method: 'POST' });
        await reloadCampaigns();
        if (requestedCampaignId === String(id)) await loadCampaign(id);
    } catch (_) {
        // apiJson already rendered the actionable error.
    } finally {
        campaignPollBusy = false;
    }
}


async function recommendParents(button) {
    return withPending('recommend-parent', button, async () => {
        const sequence = ++parentRequestSequence;
        parentController?.abort();
        parentController = new AbortController();
        try {
            const data = await apiJson('/api/campaigns/recommend-final-parents', { method: 'POST', signal: parentController.signal, body: JSON.stringify(recommendationContext()) });
            if (sequence !== parentRequestSequence) return;
            state.recommendations = Array.isArray(data.recommendation) ? data.recommendation : [];
            state.draft.selectedFinalParent = null;
            clearLoopSelection();
            renderBuilder();
        } catch (error) { if (error.name !== 'AbortError' && !els.message.textContent) showMessage(error.message, 'error'); }
    });
}

async function recommendLoops(button) {
    return withPending('recommend-loop', button, async () => {
        if (!state.draft.selectedFinalParent) { showMessage('Choose a final parent before recommending loops.', 'error'); return; }
        const sequence = ++loopRequestSequence;
        loopController?.abort();
        loopController = new AbortController();
        try {
            const payload = {
                ...recommendationContext(),
                final_parent_chara_id: Number(state.draft.selectedFinalParent.chara_id),
                pinned_chara_ids: state.draft.pinnedCharaIds,
            };
            const data = await apiJson('/api/campaigns/recommend-loop', { method: 'POST', signal: loopController.signal, body: JSON.stringify(payload) });
            if (sequence !== loopRequestSequence) return;
            const recommendation = data.recommendation || {};
            state.loopRecommendations = {
                loops: Array.isArray(recommendation.loops) ? recommendation.loops : [],
                ideal_upgrades: Array.isArray(recommendation.ideal_upgrades) ? recommendation.ideal_upgrades : [],
            };
            state.draft.selectedLoop = null; state.draft.deckAssignments = {}; state.draft.friendAssignments = {};
            renderBuilder();
        } catch (error) { if (error.name !== 'AbortError' && !els.message.textContent) showMessage(error.message, 'error'); }
    });
}

async function loadFriendSupports(button) {
    return withPending('load-friends', button, async () => {
        const data = await apiJson('/api/career/friends', {
            method: 'POST',
            body: JSON.stringify({ exclude_viewer_ids: [], force_refresh: true }),
        });
        state.friendSupports = Array.isArray(data.friends) ? data.friends : [];
        if (state.session) state.session.friends = state.friendSupports;
        renderDecks();
        renderPreview();
        showMessage(state.friendSupports.length ? `${state.friendSupports.length} friend supports loaded.` : 'No friend supports available.', state.friendSupports.length ? 'success' : 'error');
    });
}

async function saveCampaign(button) {
    return withPending('save-campaign', button, async () => {
        try {
            const data = await apiJson('/api/campaigns', { method: 'POST', body: JSON.stringify({ spec: buildSpec() }) });
            showMessage('Campaign saved.', 'success');
            await reloadCampaigns();
            els.create.hidden = true;
            await loadCampaign(data.campaign.id || data.campaign.campaign_id);
        } catch (error) { if (!els.message.textContent) showMessage(error.message, 'error'); }
    });
}

async function campaignAction(action, payload, button) {
    const id = state.selectedCampaign?.id || state.selectedCampaign?.campaign_id;
    if (!id) return;
    return withPending(`action:${id}`, button, async () => {
        try {
            await apiJson(`/api/campaigns/${encodeURIComponent(id)}/${action}`, { method: 'POST', body: payload === undefined ? undefined : JSON.stringify(payload) });
            showMessage('Campaign updated.', 'success');
            await reloadCampaigns();
            if (requestedCampaignId === String(id)) await loadCampaign(id);
        } catch (_) {}
    });
}

function bindEvents() {
    byId('new-campaign-btn').addEventListener('click', () => { resetDraft(); els.create.hidden = false; });
    byId('close-create-btn').addEventListener('click', () => { els.create.hidden = true; });
    byId('add-blue-target-btn').addEventListener('click', () => addTarget('blue'));
    byId('add-pink-target-btn').addEventListener('click', () => addTarget('pink'));
    byId('recommend-parent-btn').addEventListener('click', (event) => recommendParents(event.currentTarget));
    byId('recommend-loop-btn').addEventListener('click', (event) => recommendLoops(event.currentTarget));
    byId('recompute-loop-btn').addEventListener('click', (event) => recommendLoops(event.currentTarget));
    byId('save-campaign-btn').addEventListener('click', (event) => saveCampaign(event.currentTarget));
    els.refreshFriends.addEventListener('click', (event) => loadFriendSupports(event.currentTarget));
    els.finalUma.addEventListener('change', () => { state.draft.finalUmaCardId = Number(els.finalUma.value); clearParentAndLoop(); renderBuilder(); });
    els.preset.addEventListener('change', () => { state.draft.options.presetName = els.preset.value; renderPreview(); });
    els.maximumRuns.addEventListener('input', () => { state.draft.options.maximumRuns = Number(els.maximumRuns.value); renderPreview(); });
    els.runtime.addEventListener('input', () => { state.draft.options.maximumRuntimeHours = Number(els.runtime.value); renderPreview(); });
    els.allowRental.addEventListener('change', () => { state.draft.options.allowRental = els.allowRental.checked; renderPreview(); });
    els.autoVeteran.addEventListener('change', () => { state.draft.options.autoUseBestVeteran = els.autoVeteran.checked; renderPreview(); });
    els.stopWhenTargetReached.addEventListener('change', () => { state.draft.options.stopWhenTargetReached = els.stopWhenTargetReached.checked; renderPreview(); });
    document.addEventListener('input', (event) => {
        const row = event.target.closest('[data-target-index]');
        if (!row || !event.target.dataset.field) return;
        clearParentAndLoop();
        const target = state.draft.sparkTargets[Number(row.dataset.targetIndex)];
        target[event.target.dataset.field] = event.target.dataset.field === 'minimum_stars' ? Number(event.target.value) : event.target.value;
        renderPreview();
    });
    document.addEventListener('change', async (event) => {
        if (event.target.dataset.deckChara) {
            const charaId = Number(event.target.dataset.deckChara);
            state.draft.deckAssignments[charaId] = Number(event.target.value);
            const friend = state.draft.friendAssignments[charaId];
            if (friend && friendConflictsWithDeck(friend, event.target.value)) delete state.draft.friendAssignments[charaId];
            renderDecks(); renderPreview();
        }
        if (event.target.dataset.friendChara) {
            const charaId = Number(event.target.dataset.friendChara);
            const selected = state.friendSupports.find((friend) => friendKey(friend) === event.target.value);
            if (selected) state.draft.friendAssignments[charaId] = { ...selected };
            else delete state.draft.friendAssignments[charaId];
            renderPreview();
        }
    });
    document.addEventListener('click', async (event) => {
        const campaignItem = event.target.closest('[data-campaign-id]');
        if (campaignItem) await loadCampaign(campaignItem.dataset.campaignId);
        if (event.target.dataset.removeTarget !== undefined) { clearParentAndLoop(); state.draft.sparkTargets.splice(Number(event.target.dataset.removeTarget), 1); renderBuilder(); }
        if (event.target.dataset.parentIndex !== undefined) { state.draft.selectedFinalParent = state.recommendations[Number(event.target.dataset.parentIndex)]; clearLoopSelection(); renderBuilder(); }
        if (event.target.dataset.loopIndex !== undefined) { state.draft.selectedLoop = state.loopRecommendations.loops[Number(event.target.dataset.loopIndex)]; state.draft.deckAssignments = {}; state.draft.friendAssignments = {}; renderBuilder(); }
        if (event.target.dataset.pinId) {
            loopRequestSequence += 1; loopController?.abort();
            const id = Number(event.target.dataset.pinId);
            state.draft.pinnedCharaIds = state.draft.pinnedCharaIds.includes(id) ? state.draft.pinnedCharaIds.filter((value) => value !== id) : [...state.draft.pinnedCharaIds, id];
            state.draft.selectedLoop = null; state.draft.deckAssignments = {}; state.draft.friendAssignments = {}; renderBuilder();
        }
        if (event.target.dataset.copyUpgradeIndex !== undefined) {
            loopRequestSequence += 1; loopController?.abort();
            const upgradeIds = loopIds(state.loopRecommendations.ideal_upgrades[Number(event.target.dataset.copyUpgradeIndex)]);
            const runnableIds = new Set((state.loopRecommendations.loops || []).flatMap(loopIds));
            const ownedMatches = upgradeIds.filter((id) => runnableIds.has(id));
            state.draft.pinnedCharaIds = [...new Set([...state.draft.pinnedCharaIds, ...ownedMatches])];
            state.draft.selectedLoop = null; state.draft.deckAssignments = {}; state.draft.friendAssignments = {}; renderBuilder();
            showMessage(ownedMatches.length ? 'Owned matching members pinned. Recompute to replace unpinned members.' : 'Upgrade is non-runnable; no owned matching members can be pinned.', ownedMatches.length ? 'success' : 'error');
        }
        if (event.target.dataset.campaignAction) await campaignAction(event.target.dataset.campaignAction, event.target.dataset.campaignAction === 'approve-run' ? { selection_override: null } : event.target.dataset.campaignAction === 'cancel' ? { reason: 'Cancelled from campaigns UI' } : undefined, event.target);
        if (event.target.dataset.candidateId) await campaignAction('select-candidate', { candidate_id: event.target.dataset.candidateId }, event.target);
    });
}

async function loadRaceMetadata() {
    const response = await fetch('/assets/data/uma_race_data.json');
    if (!response.ok) throw new Error(`Race metadata failed (${response.status})`);
    const data = await response.json();
    const races = Array.isArray(data) ? data : Array.isArray(data?.races) ? data.races : [];
    state.raceById = new Map(races.map((race) => [Number(race?.program_id), race]).filter(([id]) => id > 0));
    return state.raceById;
}

async function bootstrap() {
    bindEvents(); els.create.hidden = true;
    const results = await Promise.allSettled([apiJson('/api/session'), apiJson('/api/presets'), apiJson('/api/campaigns'), loadRaceMetadata()]);
    const [sessionResult, presetResult, campaignResult] = results;
    if (sessionResult.status === 'fulfilled') {
        state.session = sessionResult.value;
        state.friendSupports = Array.isArray(sessionResult.value.friends) ? sessionResult.value.friends : [];
    }
    if (presetResult.status === 'fulfilled') state.presets = Array.isArray(presetResult.value.presets) ? presetResult.value.presets : [];
    if (campaignResult.status === 'fulfilled') {
        state.campaigns = Array.isArray(campaignResult.value.campaigns) ? campaignResult.value.campaigns : [];
        campaignAccount = accountValue(campaignResult.value.account);
    }
    renderBootstrapChoices(); resetDraft(); renderCampaignList(); renderDetail();
    const failed = results.flatMap((result, index) => result.status === 'rejected' ? [['session', 'presets', 'campaigns', 'race metadata'][index]] : []);
    if (failed.length) showMessage(`Partial load failed: ${failed.join(', ')}. Available data remains usable.`, 'error');
}

bootstrap();
setInterval(pollCampaignProgress, 5000);
