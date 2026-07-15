'use strict';

const state = {
    campaigns: [],
    selectedCampaign: null,
    recommendations: [],
    loopRecommendations: { loops: [], ideal_upgrades: [] },
    session: null,
    presets: [],
    draft: {
        finalUmaCardId: 0,
        sparkTargets: [],
        selectedFinalParent: null,
        selectedLoop: null,
        pinnedCharaIds: [],
        deckAssignments: {},
        options: {
            allowRental: false,
            autoUseBestVeteran: false,
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
const pendingMutations = new Set();

const byId = (id) => document.getElementById(id);
const els = {
    message: byId('campaign-message'), list: byId('campaign-list'), account: byId('campaign-account'),
    create: byId('campaign-create-view'), detail: byId('campaign-detail'), finalUma: byId('final-uma-select'),
    targets: byId('spark-targets'), parents: byId('parent-recommendations'), loops: byId('loop-recommendations'),
    upgrades: byId('loop-upgrades'), decks: byId('deck-assignments'), preset: byId('base-preset-select'),
    preview: byId('campaign-preview'), maximumRuns: byId('maximum-runs'), runtime: byId('maximum-runtime-hours'),
    allowRental: byId('allow-rental'), autoVeteran: byId('auto-use-best-veteran'),
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
        pinnedCharaIds: [], deckAssignments: {},
        options: { allowRental: false, autoUseBestVeteran: false, presetName: defaultPreset, maximumRuns: 30, maximumRuntimeHours: 24 },
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

function renderLoopCards(rows, upgrade = false) {
    if (!rows.length) return '<p class="empty-state">None available.</p>';
    return rows.map((loop, index) => {
        const ids = loopIds(loop);
        const selected = !upgrade && state.draft.selectedLoop === loop;
        return `<article class="recommendation-card${selected ? ' is-selected' : ''}">
            <p class="rank">#${index + 1}</p><h4>${ids.map((id) => `Chara ${id}`).join(' · ') || 'Unknown loop'}</h4>
            <p>Score ${escapeHtml(loop.score ?? '—')} · Shared G1 ${escapeHtml(loop.shared_g1_count ?? loop.score_breakdown?.shared_g1 ?? '—')}</p>
            ${upgrade ? `<span class="badge">Non-runnable upgrade suggestion</span><button class="btn btn-sm" data-copy-upgrade-index="${index}" type="button">Pin owned matching members</button>` : `<div class="pin-grid">${ids.map((id) => `<button class="btn btn-sm${state.draft.pinnedCharaIds.includes(id) ? ' btn-primary' : ''}" data-pin-id="${id}" type="button">${state.draft.pinnedCharaIds.includes(id) ? 'Unpin' : 'Pin'} Chara ${id}</button>`).join('')}</div><button class="btn btn-sm${selected ? ' btn-primary' : ''}" data-loop-index="${index}" type="button">${selected ? 'Selected' : 'Choose runnable loop'}</button>`}
        </article>`;
    }).join('');
}

function renderLoops() {
    els.loops.innerHTML = renderLoopCards(state.loopRecommendations.loops || []);
    els.upgrades.innerHTML = renderLoopCards(state.loopRecommendations.ideal_upgrades || [], true);
}

function availableDecks() {
    return (Array.isArray(state.session?.decks) ? state.session.decks : []).map((deck) => ({ id: numberFrom(deck, ['deck_id', 'id']), name: labelFor(deck, `Deck ${numberFrom(deck, ['deck_id', 'id'])}`) })).filter((deck) => deck.id >= 1 && deck.id <= 10);
}

function renderDecks() {
    const ids = loopIds(state.draft.selectedLoop);
    if (ids.length !== 4) {
        els.decks.innerHTML = '<p class="empty-state">Choose a runnable four-member loop first.</p>';
        return;
    }
    const decks = availableDecks();
    els.decks.innerHTML = ids.map((id) => `<label class="deck-row">Chara ${id}<select class="form-input" data-deck-chara="${id}"><option value="">Select deck</option>${decks.map((deck) => `<option value="${deck.id}"${Number(state.draft.deckAssignments[id]) === deck.id ? ' selected' : ''}>${escapeHtml(deck.name)} (ID ${deck.id})</option>`).join('')}</select></label>`).join('');
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
    const ids = loopIds(state.draft.selectedLoop);
    if (ids.length !== 4) throw new Error('Choose a runnable four-member loop.');
    const loopMembers = ids.map((charaId) => {
        const deckId = Number(state.draft.deckAssignments[charaId]);
        if (deckId < 1 || deckId > 10) throw new Error(`Assign a deck to Chara ${charaId}.`);
        return { chara_id: charaId, deck_id: deckId, pinned: state.draft.pinnedCharaIds.includes(charaId) };
    });
    const account = accountName();
    if (!account) throw new Error('Backend session exposes no usable campaign account name.');
    if (!state.draft.options.presetName) throw new Error('Select a persisted base preset.');
    return {
        account, spec_version: 2,
        goal: { purpose: 'parent', target_factors: [] },
        strategy: {
            preset_name: state.draft.options.presetName,
            maximum_runs: Number(state.draft.options.maximumRuns),
            maximum_runtime_hours: Number(state.draft.options.maximumRuntimeHours),
            tp_mode: 'wait', approval_mode: 'ambiguity_only', stop_when_target_reached: true,
        },
        final_uma: { card_id: context.final_uma_card_id },
        spark_targets: context.spark_targets,
        final_parent: { chara_id: Number(state.draft.selectedFinalParent.chara_id), trained_chara_id: parentTrainedId(state.draft.selectedFinalParent) },
        loop_members: loopMembers,
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

function detailActions(campaign) {
    const campaignState = String(campaign.state || campaign.status || '').toUpperCase();
    const next = campaign.next_action || '';
    const terminal = ['COMPLETED', 'CANCELLED', 'FAILED'].includes(campaignState);
    const actions = [];
    if (['DRAFT', 'READY'].includes(campaignState)) actions.push(['activate', 'Activate']);
    if (!terminal && !['DRAFT', 'PAUSED'].includes(campaignState)) actions.push(['pause', 'Pause']);
    if (campaignState === 'PAUSED') actions.push(['resume', 'Resume']);
    if (campaignState === 'SELECTING_LINEAGE' || ['prepare_next_run', 'select_lineage'].includes(next)) actions.push(['prepare-next-run', 'Prepare next run']);
    if (campaignState === 'COMPLETED') actions.push(['continue-preferred', 'Continue preferred']);
    if (!terminal) actions.push(['cancel', 'Cancel']);
    return actions.map(([action, label]) => `<button class="btn btn-sm${action === 'cancel' ? ' btn-danger-soft' : ''}" data-campaign-action="${action}" type="button">${label}</button>`).join('');
}

function renderReview(campaign) {
    const review = campaign.context?.pending_review;
    if (!review || String(campaign.state).toUpperCase() !== 'NEEDS_USER_INPUT') return '';
    if (campaign.next_action === 'select_candidate') {
        const source = Array.isArray(review.candidates) ? review.candidates : Array.isArray(campaign.candidates) ? campaign.candidates : [];
        const singleValue = review.candidate || review.candidate_id;
        const single = singleValue ? (typeof singleValue === 'object' ? singleValue : { candidate_id: singleValue }) : null;
        const allowed = Array.isArray(review.allowed_candidate_ids) ? review.allowed_candidate_ids.map((candidateId) => ({ candidate_id: candidateId })) : [];
        const candidates = [...source, ...(single ? [single] : []), ...allowed].filter((candidate, index, rows) => {
            const id = candidate?.candidate_id || candidate?.id;
            return id && rows.findIndex((row) => (row?.candidate_id || row?.id) === id) === index;
        });
        return `<section class="review-panel"><h3>Post-run Tradeoff</h3>${candidates.length ? candidates.map((candidate) => `<article class="candidate-choice"><strong>${escapeHtml(labelFor(candidate, candidate.candidate_id || 'Candidate'))}</strong><button class="btn btn-sm btn-primary" data-candidate-id="${escapeHtml(candidate.candidate_id || candidate.id)}" type="button">Choose</button></article>`).join('') : '<p class="empty-state">No selectable candidates supplied.</p>'}</section>`;
    }
    if (['approve_run', 'prepared_run'].includes(campaign.next_action)) return `<section class="review-panel"><h3>Pre-run Review</h3>${safeJson(review)}<button class="btn btn-primary" data-campaign-action="approve-run" type="button">Approve Run</button></section>`;
    return '';
}

function renderDetail() {
    const campaign = state.selectedCampaign;
    if (!campaign) { els.detail.innerHTML = '<p class="empty-state">Select a campaign.</p>'; return; }
    const spec = campaign.spec || {};
    const context = campaign.context || {};
    const agenda = context.race_agenda || context.shared_g1_agenda || campaign.race_agenda || {};
    const required = context.required_progress ?? campaign.required_progress;
    const preferred = context.preferred_progress ?? campaign.preferred_progress;
    const rotation = context.rotation || {};
    const runIndex = Number(rotation.run_index ?? context.rotation_index);
    const loopCharaIds = Array.isArray(rotation.loop_chara_ids) ? rotation.loop_chara_ids : Array.isArray(context.loop_chara_ids) ? context.loop_chara_ids : (spec.loop_members || []).map((member) => member.chara_id);
    const derivedNextTrainee = Number.isFinite(runIndex) && loopCharaIds.length ? loopCharaIds[((runIndex % loopCharaIds.length) + loopCharaIds.length) % loopCharaIds.length] : 0;
    const nextTrainee = rotation.next_trainee || context.next_trainee || derivedNextTrainee || '—';
    els.detail.innerHTML = `
        <div class="status-strip"><span class="badge">${escapeHtml(campaign.state || campaign.status || 'UNKNOWN')}</span><span>Next: ${escapeHtml(campaign.next_action || '—')}</span></div>
        <div class="detail-grid"><article><h3>Final Setup</h3><p>Uma: ${escapeHtml(spec.final_uma?.card_id || '—')}</p><p>Parent: ${escapeHtml(spec.final_parent?.chara_id || '—')} / trained ${escapeHtml(spec.final_parent?.trained_chara_id || '—')}</p></article><article><h3>Usage</h3><p>Runs: ${escapeHtml(campaign.run_count ?? context.run_count ?? 0)}</p><p>Rotation run: ${escapeHtml(Number.isFinite(runIndex) ? runIndex : '—')} · Next trainee: ${escapeHtml(nextTrainee?.name || nextTrainee?.chara_id || nextTrainee)}</p></article></div>
        <section><h3>Target Progress</h3>${progressBar('Required', required)}${progressBar('Preferred', preferred)}</section>
        ${renderReview(campaign)}
        <section><h3>Actions</h3><div class="inline-actions">${detailActions(campaign)}</div></section>
        <section><h3>Lineage &amp; Resolved Choices</h3>${safeJson(context.lineage || context.resolved_choices || campaign.lineage)}</section>
        <section><h3>Projected Final Setup</h3>${safeJson(context.projected_final_setup || campaign.projected_final_setup)}</section>
        <section><h3>Race Agenda</h3><div class="agenda-grid">${['CORE', 'OPTIONAL', 'DEFERABLE'].map((group) => `<article><h4>${group}</h4>${safeJson(agenda[group] || agenda[group.toLowerCase()])}</article>`).join('')}</div></section>
        <section><h3>Recent Events</h3>${safeJson(campaign.events || context.recent_events)}</section>
        <section><h3>Recent Candidates</h3>${safeJson(campaign.candidates || context.candidates)}</section>`;
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
            const payload = { ...recommendationContext(), pinned_chara_ids: state.draft.pinnedCharaIds };
            const data = await apiJson('/api/campaigns/recommend-loop', { method: 'POST', signal: loopController.signal, body: JSON.stringify(payload) });
            if (sequence !== loopRequestSequence) return;
            const recommendation = data.recommendation || {};
            state.loopRecommendations = {
                loops: Array.isArray(recommendation.loops) ? recommendation.loops : [],
                ideal_upgrades: Array.isArray(recommendation.ideal_upgrades) ? recommendation.ideal_upgrades : [],
            };
            state.draft.selectedLoop = null; state.draft.deckAssignments = {};
            renderBuilder();
        } catch (error) { if (error.name !== 'AbortError' && !els.message.textContent) showMessage(error.message, 'error'); }
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
    els.finalUma.addEventListener('change', () => { state.draft.finalUmaCardId = Number(els.finalUma.value); clearParentAndLoop(); renderBuilder(); });
    els.preset.addEventListener('change', () => { state.draft.options.presetName = els.preset.value; renderPreview(); });
    els.maximumRuns.addEventListener('input', () => { state.draft.options.maximumRuns = Number(els.maximumRuns.value); renderPreview(); });
    els.runtime.addEventListener('input', () => { state.draft.options.maximumRuntimeHours = Number(els.runtime.value); renderPreview(); });
    els.allowRental.addEventListener('change', () => { state.draft.options.allowRental = els.allowRental.checked; renderPreview(); });
    els.autoVeteran.addEventListener('change', () => { state.draft.options.autoUseBestVeteran = els.autoVeteran.checked; renderPreview(); });
    document.addEventListener('input', (event) => {
        const row = event.target.closest('[data-target-index]');
        if (!row || !event.target.dataset.field) return;
        clearParentAndLoop();
        const target = state.draft.sparkTargets[Number(row.dataset.targetIndex)];
        target[event.target.dataset.field] = event.target.dataset.field === 'minimum_stars' ? Number(event.target.value) : event.target.value;
        renderPreview();
    });
    document.addEventListener('change', async (event) => {
        if (event.target.dataset.deckChara) { state.draft.deckAssignments[event.target.dataset.deckChara] = Number(event.target.value); renderPreview(); }
    });
    document.addEventListener('click', async (event) => {
        const campaignItem = event.target.closest('[data-campaign-id]');
        if (campaignItem) await loadCampaign(campaignItem.dataset.campaignId);
        if (event.target.dataset.removeTarget !== undefined) { clearParentAndLoop(); state.draft.sparkTargets.splice(Number(event.target.dataset.removeTarget), 1); renderBuilder(); }
        if (event.target.dataset.parentIndex !== undefined) { state.draft.selectedFinalParent = state.recommendations[Number(event.target.dataset.parentIndex)]; clearLoopSelection(); renderBuilder(); }
        if (event.target.dataset.loopIndex !== undefined) { state.draft.selectedLoop = state.loopRecommendations.loops[Number(event.target.dataset.loopIndex)]; state.draft.deckAssignments = {}; renderBuilder(); }
        if (event.target.dataset.pinId) {
            loopRequestSequence += 1; loopController?.abort();
            const id = Number(event.target.dataset.pinId);
            state.draft.pinnedCharaIds = state.draft.pinnedCharaIds.includes(id) ? state.draft.pinnedCharaIds.filter((value) => value !== id) : [...state.draft.pinnedCharaIds, id];
            state.draft.selectedLoop = null; state.draft.deckAssignments = {}; renderBuilder();
        }
        if (event.target.dataset.copyUpgradeIndex !== undefined) {
            loopRequestSequence += 1; loopController?.abort();
            const upgradeIds = loopIds(state.loopRecommendations.ideal_upgrades[Number(event.target.dataset.copyUpgradeIndex)]);
            const runnableIds = new Set((state.loopRecommendations.loops || []).flatMap(loopIds));
            const ownedMatches = upgradeIds.filter((id) => runnableIds.has(id));
            state.draft.pinnedCharaIds = [...new Set([...state.draft.pinnedCharaIds, ...ownedMatches])];
            state.draft.selectedLoop = null; state.draft.deckAssignments = {}; renderBuilder();
            showMessage(ownedMatches.length ? 'Owned matching members pinned. Recompute to replace unpinned members.' : 'Upgrade is non-runnable; no owned matching members can be pinned.', ownedMatches.length ? 'success' : 'error');
        }
        if (event.target.dataset.campaignAction) await campaignAction(event.target.dataset.campaignAction, event.target.dataset.campaignAction === 'approve-run' ? { selection_override: null } : event.target.dataset.campaignAction === 'cancel' ? { reason: 'Cancelled from campaigns UI' } : undefined, event.target);
        if (event.target.dataset.candidateId) await campaignAction('select-candidate', { candidate_id: event.target.dataset.candidateId }, event.target);
    });
}

async function bootstrap() {
    bindEvents(); els.create.hidden = true;
    const results = await Promise.allSettled([apiJson('/api/session'), apiJson('/api/presets'), apiJson('/api/campaigns')]);
    const [sessionResult, presetResult, campaignResult] = results;
    if (sessionResult.status === 'fulfilled') state.session = sessionResult.value;
    if (presetResult.status === 'fulfilled') state.presets = Array.isArray(presetResult.value.presets) ? presetResult.value.presets : [];
    if (campaignResult.status === 'fulfilled') {
        state.campaigns = Array.isArray(campaignResult.value.campaigns) ? campaignResult.value.campaigns : [];
        campaignAccount = accountValue(campaignResult.value.account);
    }
    renderBootstrapChoices(); resetDraft(); renderCampaignList(); renderDetail();
    const failed = results.flatMap((result, index) => result.status === 'rejected' ? [['session', 'presets', 'campaigns'][index]] : []);
    if (failed.length) showMessage(`Partial load failed: ${failed.join(', ')}. Available data remains usable.`, 'error');
}

bootstrap();
