'use strict';

const state = {
    bootstrap: null,
    status: null,
    factorTargets: [],
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
    targets: byId('factor-targets'),
    reroll: byId('factor-reroll-enabled'),
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
        showMessage(error.message || 'Request failed', 'error');
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

function commaSeparatedIds(value, label) {
    const rows = String(value || '')
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
        .map((part) => asPositiveInt(part, label));
    return rows;
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

function populateChoices() {
    const bootstrap = state.bootstrap || {};
    els.trainee.innerHTML = '<option value="">Select trainee</option>'
        + (bootstrap.trainees || []).map((row) => {
            const id = traineeId(row);
            return `<option value="${id}">${escapeHtml(labelFor(row, `Trainee #${id}`))}</option>`;
        }).join('');

    const parentOptions = (bootstrap.parents || []).map((row) => {
        const id = parentId(row);
        const rank = row.rank ? ` · Rank ${row.rank}` : '';
        return `<option value="${id}">${escapeHtml(labelFor(row, `Veteran #${id}`))}${escapeHtml(rank)}</option>`;
    }).join('');
    els.parentOne.innerHTML = '<option value="">Select parent</option>' + parentOptions;
    els.parentTwo.innerHTML = '<option value="">Select parent</option>' + parentOptions;

    const supports = bootstrap.support_cards || [];
    if (!byId('support-card-ids').value && supports.length >= 5) {
        byId('support-card-ids').value = supports
            .filter((row) => !row.is_friend)
            .slice(0, 5)
            .map((row) => row.support_card_id || row.id)
            .join(', ');
    }
    const friend = supports.find((row) => row.is_friend);
    if (friend && !byId('friend-card-id').value) {
        byId('friend-card-id').value = friend.support_card_id;
    }
}

function persistConvenience() {
    const values = {
        trainee: els.trainee.value,
        parentOne: els.parentOne.value,
        parentTwo: els.parentTwo.value,
        supports: byId('support-card-ids').value,
        friendCard: byId('friend-card-id').value,
        scenario: byId('scenario-select').value,
        runningStyle: byId('running-style').value,
        deck: byId('deck-id').value,
        groundType: byId('training-policy-ground-type').value,
        rateSet: byId('training-policy-rate-set-id').value,
        useTp: byId('use-tp').value,
        prioritySkills: byId('priority-skills').value,
        raceAgenda: byId('race-agenda').value,
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
        supports: byId('support-card-ids'),
        friendCard: byId('friend-card-id'),
        scenario: byId('scenario-select'),
        runningStyle: byId('running-style'),
        deck: byId('deck-id'),
        groundType: byId('training-policy-ground-type'),
        rateSet: byId('training-policy-rate-set-id'),
        useTp: byId('use-tp'),
        prioritySkills: byId('priority-skills'),
        raceAgenda: byId('race-agenda'),
        runCount: byId('run-count'),
        tpMode: byId('tp-mode'),
    };
    Object.entries(mapping).forEach(([key, element]) => {
        if (saved[key] !== undefined && element) element.value = saved[key];
    });
    els.reroll.checked = Boolean(saved.reroll);
    state.factorTargets = Array.isArray(saved.targets) ? saved.targets : [];
    renderFactorTargets();
}

async function hydratePrivateSelection() {
    try {
        const response = await fetch('/api/session');
        const session = await response.json();
        const friend = session?.selection?.friend;
        if (session.success && friend) {
            byId('friend-viewer-id').value = friend.viewer_id || '';
            byId('friend-card-id').value = friend.support_card_id || '';
        }
    } catch (error) {
        // Manual entry remains available when no dashboard selection exists.
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

function parseRaceAgenda() {
    const raw = String(byId('race-agenda').value || '').trim();
    if (!raw) return [];
    return raw.split(',').map((entry) => {
        const [year, programId] = entry.split(':').map((value) => Number(value.trim()));
        if (![1, 2, 3].includes(year) || !Number.isInteger(programId) || programId <= 0) {
            throw new Error(`Invalid race entry "${entry.trim()}". Use year:program_id.`);
        }
        return {year, program_id: programId};
    });
}

function buildSetup() {
    const supports = commaSeparatedIds(byId('support-card-ids').value, 'Support ID');
    if (supports.length !== 5 || new Set(supports).size !== 5) {
        throw new Error('Enter exactly five distinct owned support IDs.');
    }
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
        friend_viewer_id: asPositiveInt(byId('friend-viewer-id').value, 'Friend viewer ID'),
        friend_card_id: asPositiveInt(byId('friend-card-id').value, 'Friend support ID'),
        parent_id_1: parentOne,
        parent_id_2: parentTwo,
        rental_viewer_id: 0,
        rental_trained_chara_id: 0,
        scenario_id: asPositiveInt(byId('scenario-select').value, 'Scenario'),
        deck_id: asPositiveInt(byId('deck-id').value, 'Deck ID'),
        running_style: asPositiveInt(byId('running-style').value, 'Running style'),
        training_policy_ground_type: asPositiveInt(
            byId('training-policy-ground-type').value,
            'Training policy ground type',
        ),
        training_policy_param_rate_set_id: asPositiveInt(
            byId('training-policy-rate-set-id').value,
            'Training policy rate set',
        ),
        priority_skill_array: commaSeparatedIds(
            byId('priority-skills').value,
            'Priority skill ID',
        ).map((skillId, index) => ({priority: index + 1, skill_id: skillId})),
        race_array: parseRaceAgenda(),
        factor_reroll: {enabled: els.reroll.checked, targets},
        use_tp: Number(byId('use-tp').value),
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
    const queued = runs.filter((run) => !['COMPLETED', 'CANCELLED'].includes(run.state));
    const completed = runs.filter((run) => run.state === 'COMPLETED').slice(-10).reverse();

    els.account.textContent = status.account || state.bootstrap?.account_label || 'No bound account';
    els.executor.textContent = runner.state || 'IDLE';
    els.executor.className = `state-badge is-${stateClass(runner.state)}`;

    if (!active) {
        els.active.innerHTML = `<p class="empty-state">No active run. Executor: ${escapeHtml(runner.state || 'IDLE')}.</p>`;
    } else {
        const end = Number(active.server_end_time || 0) * 1000;
        const remaining = end ? Math.max(0, end - Date.now()) : 0;
        const timeLabel = end && remaining > 0 ? formatDuration(remaining) : 'Checking server';
        els.active.innerHTML = `
            <article class="active-summary">
                <div><span>Run</span><strong>${escapeHtml(runTitle(active))}</strong><small>${escapeHtml(active.run_id)}</small></div>
                <div><span>State</span><strong class="run-state is-${stateClass(active.state)}">${escapeHtml(active.state)}</strong></div>
                <div><span>Server ETA</span><strong>${escapeHtml(timeLabel)}</strong><small>Countdown is display-only</small></div>
                <div><span>Next action</span><strong>${escapeHtml(active.next_action || 'Automatic')}</strong><small>${escapeHtml(active.error || '')}</small></div>
            </article>
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
    state.bootstrap = await apiJson('/api/independent-training/bootstrap');
    state.status = state.bootstrap.status || null;
    populateChoices();
    restoreConvenience();
    await hydratePrivateSelection();
    renderStatus();
}

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

els.queue.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-cancel-run]');
    if (!button) return;
    await apiJson(`/api/independent-training/runs/${encodeURIComponent(button.dataset.cancelRun)}`, {
        method: 'DELETE',
    });
    showMessage('Queued run removed.', 'success');
    await refreshStatus();
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
