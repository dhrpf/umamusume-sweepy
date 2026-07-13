(() => {
const scenarioTypes = { 1: "Ura", 2: "Unity", 4: "Mant" };

const state = {
    needs2fa: false,
    isLoading: false,
    account: null,
    isDeletingCareer: false,
    isFetchingFriends: false,
    isStartingCareer: false,
    presets: [],
    selectedPreset: "",
    runnerTimer: 0,
    isSavingPreset: false,
    raceData: [],
    selectedRaces: [],
    scenarioType: "Mant",
    burnClocks: false,
    displayedClocksUsed: 0,
    devEnabled: true,
    consecutiveRunnerFails: 0,
    friendTypeFilter: "",
    parentNameFilter: "",
    parentSparkFilters: {},
    veteranPageSelected: new Set(),
    veteranPageQuery: '',
    veteranSort: 'date_desc',
    isRemovingVeterans: false,
};
const els = {
    loadingScreen: document.getElementById('loading-screen'),
    navbar: document.querySelector('.navbar'),
    themeToggle: document.getElementById('theme-toggle'),
    brandMark: document.querySelector('.title span'),
    loginBtn: document.getElementById('login-btn'),
    logoutBtn: document.getElementById('logout-btn'),
    dashboardNavBtn: document.getElementById('dashboard-nav-btn'),
    dailiesNavBtn: document.getElementById('dailies-nav-btn'),
    veteranNavBtn: document.getElementById('veteran-nav-btn'),
    dailiesView: document.getElementById('dailies-view'),
    dailiesRun: document.getElementById('dailies-run'),
    dailiesStop: document.getElementById('dailies-stop'),
    dailiesLive: document.getElementById('dailies-live'),
    dailiesLiveText: document.getElementById('dailies-live-text'),
    dailiesTask: document.getElementById('dailies-task'),
    dailiesLog: document.getElementById('dailies-log'),
    dailyTeamTrials: document.getElementById('daily-team-trials'),
    dailyDailyRaces: document.getElementById('daily-daily-races'),
    dailyLegendRaces: document.getElementById('daily-legend-races'),
    dailyShop: document.getElementById('daily-shop'),
    dailyVeteran: document.getElementById('daily-veteran'),
    dailyOpponent: document.getElementById('daily-opponent'),
    dailyLegendId: document.getElementById('daily-legend-id'),
    veteranView: document.getElementById('veteran-view'),
    veteranPageGrid: document.getElementById('veteran-page-grid'),
    veteranPageCount: document.getElementById('veteran-page-count'),
    veteranPageStatus: document.getElementById('veteran-page-status'),
    veteranPageSearch: document.getElementById('veteran-page-search'),
    veteranSortSelect: document.getElementById('veteran-sort-select'),
    veteranSelectAllBtn: document.getElementById('veteran-select-all-btn'),
    veteranClearBtn: document.getElementById('veteran-clear-btn'),
    veteranRemoveBtn: document.getElementById('veteran-remove-btn'),
    veteranDetailBackdrop: document.getElementById('veteran-detail-backdrop'),
    veteranDetailDrawer: document.getElementById('veteran-detail-drawer'),
    veteranDetailClose: document.getElementById('veteran-detail-close'),
    veteranDetailContent: document.getElementById('veteran-detail-content'),
    turnDelayMin: document.getElementById('turn-delay-min'),
    turnDelayMax: document.getElementById('turn-delay-max'),
    temptFateBtn: document.getElementById('tempt-fate-btn'),
    burnClocksBtn: document.getElementById('burn-clocks-btn'),
    devBtn: document.getElementById('dev-career-btn'),
    loginView: document.getElementById('login-view'),
    dashboardView: document.getElementById('dashboard-view'),
    errorMsg: document.getElementById('error-msg'),
    standardFields: document.getElementById('standard-fields'),
    faFields: document.getElementById('2fa-fields'),
    umaGrid: document.getElementById('uma-grid'),
    cardGrid: document.getElementById('card-grid'),
    cardGridWrapper: document.getElementById('card-grid-wrapper'),
    cardsToggle: document.getElementById('cards-toggle'),
    cardsChevron: document.getElementById('cards-chevron'),
    parentGrid: document.getElementById('parent-grid'),
    friendGrid: document.getElementById('friend-grid'),
    deckList: document.getElementById('deck-list'),
    umaCount: document.getElementById('uma-count'),
    cardCount: document.getElementById('card-count'),
    parentCount: document.getElementById('parent-count'),
    friendCount: document.getElementById('friend-count'),
    friendStatus: document.getElementById('friend-status'),
    friendRefreshBtn: document.getElementById('friend-refresh-btn'),
    presetSelect: document.getElementById('preset-select'),
    startCareerBtn: document.getElementById('start-career-btn'),
    startStatus: document.getElementById('start-status'),
    accountStrip: document.getElementById('account-strip'),
    careerModal: document.getElementById('career-modal'),
    careerModalCopy: document.getElementById('career-modal-copy'),
    careerCancelBtn: document.getElementById('career-cancel-btn'),
    careerDeleteBtn: document.getElementById('career-delete-btn'),
    raceToggle: document.getElementById('race-toggle'),
    raceChevron: document.getElementById('race-chevron'),
    raceBody: document.getElementById('race-body'),
    saveRacesBtn: document.getElementById('save-races-btn'),
    raceOptionsContent: document.getElementById('race-options-content'),
    racePopupOverlay: document.getElementById('race-slot-popup-overlay'),
    racePopupTitle: document.getElementById('race-slot-popup-title'),
    racePopupBody: document.getElementById('race-slot-popup-body'),
    racePopupClose: document.getElementById('race-slot-popup-close'),
    masterDataPath: document.getElementById('master-data-path'),
    masterDataSaveBtn: document.getElementById('master-data-save-btn'),
    masterDataStatus: document.getElementById('master-data-status'),
    presetSection: document.getElementById('preset-section'),
    presetAddBtn: document.getElementById('preset-add-btn'),
    presetDelBtn: document.getElementById('preset-del-btn'),
    presetRunningStyle: document.getElementById('preset-running-style'),
    presetSkillThreshold: document.getElementById('preset-skill-threshold'),
    presetDelayMin: document.getElementById('preset-delay-min'),
    presetDelayMax: document.getElementById('preset-delay-max'),
    presetTpMode: document.getElementById('preset-tp-mode'),
    presetScenario: document.getElementById('preset-scenario'),
    unityTrainingWeight: document.getElementById('unity-training-weight'),
    unityBurstWeight: document.getElementById('unity-burst-weight'),
    presetUseMcts: document.getElementById('preset-use-mcts'),
    presetPalRecreation: document.getElementById('preset-pal-recreation'),
    presetParentRun: document.getElementById('preset-parent-run'),
    presetEditSkillsBtn: document.getElementById('preset-edit-skills-btn'),
    presetExpectSpeed: document.getElementById('preset-expect-speed'),
    presetExpectStamina: document.getElementById('preset-expect-stamina'),
    presetExpectPower: document.getElementById('preset-expect-power'),
    presetExpectGuts: document.getElementById('preset-expect-guts'),
    presetExpectWit: document.getElementById('preset-expect-wit'),
    skillModal: document.getElementById('skill-modal'),
    skillSearch: document.getElementById('skill-search'),
    skillList: document.getElementById('skill-list'),
    skillTiersContainer: document.getElementById('skill-tiers-container'),
    skillBlacklistContainer: document.getElementById('skill-blacklist-container'),
    skillAddTierBtn: document.getElementById('skill-add-tier-btn'),
    skillModalClose: document.getElementById('skill-modal-close'),
    inheritancePool: document.getElementById('inheritance-pool'),
    inheritanceDistance: document.getElementById('inheritance-distance'),
    inheritanceSurface: document.getElementById('inheritance-surface'),
    inheritanceRecommendBtn: document.getElementById('inheritance-recommend-btn'),
    inheritanceStatus: document.getElementById('inheritance-status'),
    inheritanceResults: document.getElementById('inheritance-results'),
    friendVetGrid: document.getElementById('friend-vet-grid'),
    friendVetCount: document.getElementById('friend-vet-count'),
    friendVetStatus: document.getElementById('friend-vet-status'),
    friendVetRefreshBtn: document.getElementById('friend-vet-refresh-btn'),
    friendVetSearch: document.getElementById('friend-vet-search-input'),
    friendVetRank: document.getElementById('friend-vet-rank-select'),
    friendVetSparkToggle: document.getElementById('friend-vet-spark-toggle'),
    friendVetSparkDrawer: document.getElementById('friend-vet-spark-drawer'),
    friendVetsToggle: document.getElementById('friend-vets-toggle'),
    friendVetsChevron: document.getElementById('friend-vets-chevron'),
    friendVetsBody: document.getElementById('friend-vets-body'),
    friendIdInput: document.getElementById('friend-id-input'),
    friendPreviewBtn: document.getElementById('friend-preview-btn'),
    friendFollowBtn: document.getElementById('friend-follow-btn'),
    friendPreviewPanel: document.getElementById('friend-preview-panel'),
    friendManageStatus: document.getElementById('friend-manage-status'),
    friendManageList: document.getElementById('friend-manage-list'),
    advisorPanel: document.getElementById('advisor-panel'),
    aptitudePanel: document.getElementById('aptitude-panel'),
    aptitudeBars: document.getElementById('aptitude-bars'),
    traineeAptPanel: document.getElementById('trainee-aptitude-panel'),
    traineeAptTable: document.getElementById('trainee-aptitude-table'),};
        const delaySettingsStorageKey = 'uma_turn_delay_settings';
        const burnClocksStorageKey = 'uma_burn_clocks';
        const devStorageKey = 'uma_dev_career';
        function syncDevControls() {
            if (!els.devBtn) return;
            els.devBtn.classList.toggle('is-active', state.devEnabled);
            els.devBtn.innerText = `DEV: ${state.devEnabled ? 'ON' : 'OFF'}`;
        }
        function setDevEnabled(value, options = {}) {
            state.devEnabled = Boolean(value);
            syncDevControls();
            if (options.persist) {
                localStorage.setItem(devStorageKey, String(state.devEnabled));
            }
        }

        window.addEventListener('storage', event => {
            if (event.key === devStorageKey && event.newValue !== null) {
                setDevEnabled(event.newValue === 'true', { persist: false });
            }
        });
        const storedDev = localStorage.getItem(devStorageKey);
        if (storedDev !== null) setDevEnabled(storedDev === 'true', { persist: false });
        else setDevEnabled(true, { persist: true });

        if (els.inheritanceRecommendBtn) els.inheritanceRecommendBtn.addEventListener('click', recommendInheritance);

        if (els.devBtn) {
            els.devBtn.addEventListener('click', () => {
                setDevEnabled(!state.devEnabled, { persist: true });
                syncStartButton();
            });
        }

        function setLoadingScreen(visible) {
            if (!els.loadingScreen) return;
            els.loadingScreen.classList.toggle('hidden', !visible);
        }
        function hideNavbar() {
            document.body.classList.add('pre-login');
            if (els.brandMark) els.brandMark.classList.remove('is-entrance');
        }
        function showNavbar() {
            document.body.classList.remove('pre-login');
        }
        function playBrandIntro() {
            if (!els.brandMark) return;
            els.brandMark.classList.remove('is-entrance');
            void els.brandMark.offsetWidth;
            els.brandMark.classList.add('is-entrance');
            window.setTimeout(() => els.brandMark.classList.remove('is-entrance'), 950);
        }
        hideNavbar();
        function syncDashboardHeight() {
            const navbar = document.querySelector('.navbar');
            const navbarHeight = navbar ? navbar.getBoundingClientRect().height : 0;
            const availableHeight = Math.max(360, Math.floor(window.innerHeight - navbarHeight));
            document.documentElement.style.setProperty('--dashboard-height', `${availableHeight}px`);
            syncDashboardCollapseState(false);
        }
        window.addEventListener('resize', syncDashboardHeight);
        window.addEventListener('orientationchange', syncDashboardHeight);
        syncDashboardHeight();
        const panelToggleSyncers = [];
        const dashboardMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
        let dashboardLayoutAnimation = 0;
        const dashboardAnimationMs = 420;
        function isCompactDashboard() {
            return window.matchMedia('(max-width: 850px)').matches;
        }
        function getPanelLayoutTarget(setupCollapsed, contentCollapsed) {
            const compact = isCompactDashboard();
            const gutter = document.querySelector('.split-gutter-controls');
            const dashboardRect = els.dashboardView.getBoundingClientRect();
            const gutterRect = gutter.getBoundingClientRect();
            const gutterSize = compact ? gutterRect.height : gutterRect.width;
            const available = Math.max(0, (compact ? dashboardRect.height : dashboardRect.width) - gutterSize);
            if (compact) {
                const setupSize = setupCollapsed ? 0 : contentCollapsed ? available : available * 0.34;
                const contentSize = contentCollapsed ? 0 : setupCollapsed ? available : Math.max(340, available - setupSize);
                return { compact, gutterSize, setupSize, contentSize };
            }
            const setupSize = setupCollapsed ? 0 : contentCollapsed ? available : Math.min(available * 0.62, available - 340);
            const contentSize = contentCollapsed ? 0 : setupCollapsed ? available : Math.max(340, available - setupSize);
            return { compact, gutterSize, setupSize, contentSize };
        }
        function setDashboardTemplate(layout, setupSize, contentSize) {
            const safeSetup = Math.max(0, setupSize);
            const safeContent = Math.max(0, contentSize);
            if (layout.compact) {
                els.dashboardView.style.gridTemplateColumns = '';
                els.dashboardView.style.gridTemplateRows = `${safeSetup}px ${layout.gutterSize}px ${safeContent}px`;
            } else {
                els.dashboardView.style.gridTemplateRows = '';
                els.dashboardView.style.gridTemplateColumns = `${safeSetup}px ${layout.gutterSize}px ${safeContent}px`;
            }
        }
        function easeDashboardLayout(t) {
            return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        }
        function syncDashboardCollapseState(animate = false) {
            const setupPanel = document.getElementById('setup-panel');
            const contentPanel = document.getElementById('content-panel');
            if (!setupPanel || !contentPanel || !els.dashboardView) return;
            if (setupPanel.classList.contains('collapsed') && contentPanel.classList.contains('collapsed')) {
                contentPanel.classList.remove('collapsed');
            }
            const setupCollapsed = setupPanel.classList.contains('collapsed');
            const contentCollapsed = contentPanel.classList.contains('collapsed');
            els.dashboardView.classList.toggle('setup-collapsed', setupCollapsed);
            els.dashboardView.classList.toggle('content-collapsed', contentCollapsed);
            if (!els.dashboardView.classList.contains('active')) return;
            const layout = getPanelLayoutTarget(setupCollapsed, contentCollapsed);
            if (dashboardLayoutAnimation) {
                cancelAnimationFrame(dashboardLayoutAnimation);
                dashboardLayoutAnimation = 0;
            }
            els.dashboardView.style.transition = 'none';
            if (!animate || dashboardMotion.matches) {
                setDashboardTemplate(layout, layout.setupSize, layout.contentSize);
                return;
            }
            const compact = layout.compact;
            const setupRect = setupPanel.getBoundingClientRect();
            const contentRect = contentPanel.getBoundingClientRect();
            const startSetup = compact ? setupRect.height : setupRect.width;
            const startContent = compact ? contentRect.height : contentRect.width;
            const targetSetup = layout.setupSize;
            const targetContent = layout.contentSize;
            if (Math.abs(startSetup - targetSetup) < 0.5 && Math.abs(startContent - targetContent) < 0.5) {
                setDashboardTemplate(layout, targetSetup, targetContent);
                return;
            }
            const startedAt = performance.now();
            const step = now => {
                const t = Math.min(1, (now - startedAt) / dashboardAnimationMs);
                const eased = easeDashboardLayout(t);
                setDashboardTemplate(
                    layout,
                    startSetup + (targetSetup - startSetup) * eased,
                    startContent + (targetContent - startContent) * eased
                );
                if (t < 1) {
                    dashboardLayoutAnimation = requestAnimationFrame(step);
                } else {
                    setDashboardTemplate(layout, targetSetup, targetContent);
                    dashboardLayoutAnimation = 0;
                }
            };
            setDashboardTemplate(layout, startSetup, startContent);
            dashboardLayoutAnimation = requestAnimationFrame(step);
        }
        function syncPanelToggleButtons() {
            panelToggleSyncers.forEach(sync => sync());
        }
        function makePanelToggle(panelId, btnId, collapseIcon, expandIcon) {
            const panel = document.getElementById(panelId);
            const btn = document.getElementById(btnId);
            const label = (btn.dataset.panelLabel || 'panel').toLowerCase();
            const renderChevrons = icon => `
                <span class="panel-collapse-btn-chevron-stack" aria-hidden="true">
                    <span>${icon}</span>
                    <span>${icon}</span>
                    <span>${icon}</span>
                </span>
            `;
            const syncButton = () => {
                const isCollapsed = panel.classList.contains('collapsed');
                const icon = isCollapsed ? expandIcon : collapseIcon;
                btn.classList.toggle('is-collapsed', isCollapsed);
                btn.innerHTML = renderChevrons(icon);
                btn.setAttribute('title', `${isCollapsed ? 'Expand' : 'Collapse'} ${label}`);
                btn.setAttribute('aria-label', `${isCollapsed ? 'Expand' : 'Collapse'} ${label}`);
                btn.setAttribute('aria-expanded', String(!isCollapsed));
            };
            panelToggleSyncers.push(syncButton);
            btn.addEventListener('click', () => {
                panel.classList.toggle('collapsed');
                syncDashboardCollapseState(true);
                syncPanelToggleButtons();
            });
            syncDashboardCollapseState(false);
            syncButton();
        }
        makePanelToggle('setup-panel',   'setup-collapse-btn',   '&lt;', '&gt;');
        makePanelToggle('content-panel', 'content-collapse-btn', '&gt;', '&lt;');
        function makeSectionToggle(toggleId, chevronId, bodyId, startExpanded) {
            const toggle  = document.getElementById(toggleId);
            const chevron = document.getElementById(chevronId);
            const body    = document.getElementById(bodyId);
            if (!toggle || !body) return;
            const setInitial = () => {
                const expanded = body.classList.contains('expanded');
                body.style.height = expanded ? 'auto' : '0px';
                chevron.classList.toggle('expanded', expanded);
            };
            const expand = () => {
                body.classList.add('expanded');
                chevron.classList.add('expanded');
                body.style.height = '0px';
                body.offsetHeight;
                body.style.height = `${body.scrollHeight}px`;
            };
            const collapse = () => {
                body.style.height = `${body.scrollHeight}px`;
                body.offsetHeight;
                body.classList.remove('expanded');
                chevron.classList.remove('expanded');
                body.style.height = '0px';
            };
            body.addEventListener('transitionend', event => {
                if (event.propertyName === 'height' && body.classList.contains('expanded')) body.style.height = 'auto';
            });
            toggle.addEventListener('click', () => {
                if (body.classList.contains('expanded')) collapse();
                else expand();
            });
            setInitial();
        }
        makeSectionToggle('decks-toggle',    'decks-chevron',    'decks-body',    true);
        makeSectionToggle('friends-toggle',  'friends-chevron',  'friends-body',  true);
        makeSectionToggle('trainees-toggle', 'trainees-chevron', 'trainees-body', true);
        makeSectionToggle('parents-toggle',  'parents-chevron',  'parents-body',  true);
        makeSectionToggle('cards-toggle',    'cards-chevron',    'card-grid-wrapper', false);
        const applyTheme = theme => {
            const nextTheme = theme === 'blue' ? 'blue' : 'pink';
            document.documentElement.dataset.theme = nextTheme;
            document.documentElement.classList.toggle('theme-blue', nextTheme === 'blue');
            document.body.classList.toggle('theme-blue', nextTheme === 'blue');
            return nextTheme;
        };
        applyTheme(localStorage.getItem('theme'));
        const savedUsername = localStorage.getItem('saved_username');
        const savedPassword = localStorage.getItem('saved_password');
        if (savedUsername) document.getElementById('username').value = savedUsername;
        if (savedPassword) document.getElementById('password').value = savedPassword;
        let themeToggleClicks = 0;
        els.themeToggle.addEventListener('click', () => {
            const nextTheme = document.body.classList.contains('theme-blue') ? 'pink' : 'blue';
            applyTheme(nextTheme);
            localStorage.setItem('theme', nextTheme);
            themeToggleClicks++;
            if (themeToggleClicks >= 11 && els.devBtn) {
                els.devBtn.style.display = 'inline-block';
            }
        });
        window.iwillnotabusethis = function() {
            if (els.devBtn) els.devBtn.style.display = 'inline-block';
            setDevEnabled(true, { persist: true });
        };
        const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));
        const nextFrame = () => new Promise(resolve => requestAnimationFrame(resolve));
        async function waitForDomPaint(frames = 2) {
            for (let i = 0; i < frames; i++) await nextFrame();
        }
        async function apiJson(url, options = {}) {
            const res = await fetch(url, options);
            return res.json();
        }
        function setMasterDataStatus(message, stateName = '') {
            if (!els.masterDataStatus) return;
            els.masterDataStatus.textContent = message || '';
            els.masterDataStatus.className = `master-data-status ${stateName}`.trim();
        }
        function applyMasterDataStatus(data) {
            if (!data) return;
            if (els.masterDataPath && data.master_mdb_path) {
                els.masterDataPath.value = data.master_mdb_path;
            }
            if (els.masterDataPath) {
                els.masterDataPath.classList.toggle('needs-action', !data.exists);
            }
            if (data.exists) {
                if (data.generation_error) {
                    setMasterDataStatus(data.generation_error, 'needs-action');
                } else if (data.generated) {
                    setMasterDataStatus('master.mdb found; data generated', 'ok');
                } else {
                    setMasterDataStatus('master.mdb found', 'ok');
                }
            } else {
                setMasterDataStatus(data.access_error || 'master.mdb not found; update the path', 'needs-action');
            }
        }
        async function loadMasterDataStatus() {
            if (!els.masterDataPath) return;
            try {
                applyMasterDataStatus(await apiJson('/api/master-data/status'));
            } catch (e) {
                setMasterDataStatus('Unable to read master data status', 'needs-action');
            }
        }
        async function saveMasterDataPath() {
            if (!els.masterDataPath) return null;
            const master_mdb_path = els.masterDataPath.value.trim();
            if (!master_mdb_path) {
                setMasterDataStatus('Enter the full path to master.mdb', 'needs-action');
                els.masterDataPath.classList.add('needs-action');
                return null;
            }
            if (els.masterDataSaveBtn) els.masterDataSaveBtn.disabled = true;
            setMasterDataStatus('Saving path and generating data...', 'working');
            const data = await apiJson('/api/master-data/path', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ master_mdb_path })
            });
            applyMasterDataStatus(data);
            if (data.exists && !data.generation_error) {
                await loadRaceData();
            }
            if (els.masterDataSaveBtn) els.masterDataSaveBtn.disabled = false;
            return data;
        }
        function bindMasterDataControls() {
            if (!els.masterDataPath) return;
            if (els.masterDataSaveBtn) {
                els.masterDataSaveBtn.addEventListener('click', async () => {
                    try {
                        await saveMasterDataPath();
                    } catch (e) {
                        setMasterDataStatus(e.message || 'Unable to save master.mdb path', 'needs-action');
                        if (els.masterDataPath) els.masterDataPath.classList.add('needs-action');
                    } finally {
                        if (els.masterDataSaveBtn) els.masterDataSaveBtn.disabled = false;
                    }
                });
            }
            els.masterDataPath.addEventListener('input', () => {
                els.masterDataPath.classList.remove('needs-action');
            });
            loadMasterDataStatus();
        }
        function writeLocalSetting(key, value) {
            try {
                localStorage.setItem(key, JSON.stringify(value));
            } catch (e) {}
        }
        function readLocalSetting(value, fallback = null) {
            if (!value) return fallback;
            try {
                return JSON.parse(value);
            } catch (e) {
                return fallback;
            }
        }
        function escapeHtml(value) {
            return String(value ?? '').replace(/[&<>"']/g, char => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            }[char]));
        }
        function escapeAttr(value) {
            return escapeHtml(value);
        }
        function normalizeDelayBounds(min, max, disabled = false, restoreMin = null, restoreMax = null) {
            const fallbackMin = Number.isFinite(Number(restoreMin)) ? Number(restoreMin) : 1.6;
            const fallbackMax = Number.isFinite(Number(restoreMax)) ? Number(restoreMax) : 3.7;
            if (disabled) return { min: 0, max: 0, restoreMin: fallbackMin, restoreMax: fallbackMax, disabled: true };
            const left = Math.max(0, Number.isFinite(Number(min)) ? Number(min) : fallbackMin);
            let right = Math.max(0, Number.isFinite(Number(max)) ? Number(max) : fallbackMax);
            if (left > right) right = left;
            return { min: left, max: right, restoreMin: left, restoreMax: right, disabled: false };
        }
        function setDelayControls(settings) {
            if (!els.turnDelayMin || !els.turnDelayMax || !els.temptFateBtn) return;
            const disabled = Boolean(settings.disabled);
            const restoreMin = Number.isFinite(Number(settings.restoreMin)) ? Number(settings.restoreMin) : Number(settings.restore_min);
            const restoreMax = Number.isFinite(Number(settings.restoreMax)) ? Number(settings.restoreMax) : Number(settings.restore_max);
            els.turnDelayMin.value = String(settings.min);
            els.turnDelayMax.value = String(settings.max);
            els.turnDelayMin.dataset.restoreValue = String(Number.isFinite(restoreMin) ? restoreMin : settings.min);
            els.turnDelayMax.dataset.restoreValue = String(Number.isFinite(restoreMax) ? restoreMax : settings.max);
            els.turnDelayMin.disabled = disabled;
            els.turnDelayMax.disabled = disabled;
            els.temptFateBtn.classList.toggle('is-active', disabled);
            els.temptFateBtn.innerText = disabled ? 'FATE TEMPTED' : 'TEMPT FATE';
        }
        async function saveDelaySettings(settings) {
            setDelayControls(settings);
            const data = await apiJson('/api/settings/turn-delay', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            const normalized = normalizeDelayBounds(data.min, data.max, data.disabled, data.restore_min, data.restore_max);
            setDelayControls(normalized);
            writeLocalSetting(delaySettingsStorageKey, normalized);
        }
        async function loadDelaySettings() {
            if (!els.turnDelayMin || !els.turnDelayMax || !els.temptFateBtn) return;
            try {
                const data = await apiJson('/api/settings/turn-delay');
                setDelayControls(normalizeDelayBounds(data.min, data.max, data.disabled, data.restore_min, data.restore_max));
            } catch (e) {
                setDelayControls({ min: 1.6, max: 3.7, restoreMin: 1.6, restoreMax: 3.7, disabled: false });
            }
        }
        function bindDelayControls() {
            if (!els.turnDelayMin || !els.turnDelayMax || !els.temptFateBtn) return;
            const sync = () => {
                saveDelaySettings(normalizeDelayBounds(els.turnDelayMin.value, els.turnDelayMax.value, false));
                if (state.selectedPreset) savePresetConfig();
            };
            els.turnDelayMin.addEventListener('input', sync);
            els.turnDelayMax.addEventListener('input', sync);
            els.temptFateBtn.addEventListener('click', () => {
                const active = els.temptFateBtn.classList.contains('is-active');
                const restoreMin = Number(els.turnDelayMin.dataset.restoreValue || 1.6);
                const restoreMax = Number(els.turnDelayMax.dataset.restoreValue || 3.7);
                saveDelaySettings(active
                    ? normalizeDelayBounds(restoreMin, restoreMax, false)
                    : normalizeDelayBounds(0, 0, true, restoreMin, restoreMax)
                );
                if (state.selectedPreset) savePresetConfig();
            });
            loadDelaySettings();
        }
        window.addEventListener('storage', event => {
            if (event.key !== delaySettingsStorageKey || !event.newValue) return;
            const settings = readLocalSetting(event.newValue);
            if (settings) setDelayControls(normalizeDelayBounds(settings.min, settings.max, settings.disabled, settings.restoreMin, settings.restoreMax));
        });
        window.addEventListener('storage', event => {
            if (event.key !== burnClocksStorageKey || !event.newValue) return;
            setBurnClocks(readLocalSetting(event.newValue, false));
        });
        function resetLoginState() {
            state.isLoading = false;
            els.loginBtn.innerText = state.needs2fa ? 'VALIDATE' : 'LOGIN';
        }
        function showLoginError(message) {
            setLoadingScreen(false);
            els.errorMsg.innerText = String(message || 'FAIL').toUpperCase();
            els.errorMsg.style.display = 'block';
            resetLoginState();
        }
        function showTwoFactorPrompt() {
            setLoadingScreen(false);
            state.needs2fa = true;
            state.isLoading = false;
            els.standardFields.style.display = 'none';
            els.faFields.style.display = 'block';
            els.loginBtn.innerText = 'VALIDATE';
            els.errorMsg.innerText = '2FA REQUIRED';
            els.errorMsg.style.display = 'block';
        }
        function readLoginPayload() {
            return {
                username: document.getElementById('username').value,
                password: document.getElementById('password').value,
                code: document.getElementById('code').value
            };
        }
        function resetSelection() {
            selection.deck = null;
            selection.friend = null;
            selection.trainee = null;
            selection.veterans = [];
        }
        function hideBrokenImage(img) {
            img.onerror = null;
            img.style.display = 'none';
        }
        function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
        const loginForm = document.getElementById('login-form');
        loginForm.addEventListener('submit', async event => {
            event.preventDefault();
            if (state.isLoading) return;
            state.isLoading = true;
            setLoadingScreen(true);
            els.loginBtn.innerText = 'WORKING...';
            els.errorMsg.style.display = 'none';
            const payload = readLoginPayload();
            try {
                const data = await apiJson('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (data.needs_2fa) {
                    showTwoFactorPrompt();
                } else if (data.success) {
                    localStorage.setItem('saved_username', payload.username);
                    localStorage.setItem('saved_password', payload.password);
                    await renderDashboard(data, { animateIntro: true, waitForIntro: true });
                    state.isLoading = false;
                } else {
                    showLoginError(data.detail || 'FAIL');
                }
            } catch (e) {
                showLoginError('NETWORK ERROR');
            }
        });

        els.logoutBtn.addEventListener('click', async () => {
            setLoadingScreen(false);
            try {
                await apiJson('/api/logout', { method: 'POST' });
            } catch (e) {}
            document.body.classList.remove('dashboard-mode');
            hideNavbar();
            els.loginView.style.display = 'flex';
            els.dashboardView.style.display = 'none';
            els.dashboardView.classList.remove('active');
            if (els.veteranView) els.veteranView.style.display = 'none';
            document.body.classList.remove('veteran-mode');
            els.logoutBtn.style.display = 'none';
            if (els.dashboardNavBtn) els.dashboardNavBtn.style.display = 'none';
            if (els.veteranNavBtn) els.veteranNavBtn.style.display = 'none';
            els.standardFields.style.display = 'block';
            els.faFields.style.display = 'none';
            els.loginBtn.innerText = 'LOGIN';
            els.accountStrip.style.display = 'none';
            els.accountStrip.innerHTML = '';
            state.account = null;
            state.needs2fa = false;
            dashData = null;
            resetSelection();
            syncDashboardHeight();
            loginForm.reset();
        });

        const formatNumber = value => Number(value || 0).toLocaleString();
        function closeCareerModal() {
            els.careerModal.style.display = 'none';
            els.careerModalCopy.innerText = 'This will force-delete the ongoing career.';
            els.careerDeleteBtn.innerText = 'DELETE';
            state.isDeletingCareer = false;
        }
        function openCareerModal() {
            const career = state.account && state.account.career;
            if (!career || !career.active) return;
            els.careerModalCopy.innerText = 'This will force-delete the ongoing career.';
            els.careerModal.style.display = 'flex';
        }
        async function deleteCareer() {
            const career = state.account && state.account.career;
            if (!career || !career.active || state.isDeletingCareer) return;
            state.isDeletingCareer = true;
            els.careerDeleteBtn.innerText = 'DELETING';
            els.careerModalCopy.innerText = 'Deleting ongoing career...';
            try {
                const data = await apiJson('/api/career/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ current_turn: career.turn || 0 })
                });
                if (!data.success) throw new Error(data.detail || 'Delete failed');
                renderAccountStrip(data.account);
                closeCareerModal();
            } catch (e) {
                els.careerModalCopy.innerText = e.message || 'Delete failed';
                els.careerDeleteBtn.innerText = 'RETRY';
                state.isDeletingCareer = false;
            }
        }
        els.careerCancelBtn.addEventListener('click', closeCareerModal);
        els.careerDeleteBtn.addEventListener('click', deleteCareer);
        els.careerModal.addEventListener('click', event => {
            if (event.target === els.careerModal) closeCareerModal();
        });
        function syncBurnClocksControls() {
            if (!els.burnClocksBtn) return;
            const clocks = state.account ? Number(state.account.clocks || 0) : 0;
            const disabled = clocks <= 11;

            if (disabled) {
                state.burnClocks = false;
                els.burnClocksBtn.disabled = true;
                els.burnClocksBtn.classList.remove('is-active');
                els.burnClocksBtn.innerText = `BURN CLOCKS: LOW (${clocks})`;
            } else {
                els.burnClocksBtn.disabled = false;
                els.burnClocksBtn.classList.toggle('is-active', state.burnClocks);
                els.burnClocksBtn.innerText = `BURN CLOCKS: ${state.burnClocks ? 'ON' : 'OFF'}`;
            }
        }
        function setBurnClocks(value, options = {}) {
            state.burnClocks = Boolean(value);
            syncBurnClocksControls();
            if (options.persist) writeLocalSetting(burnClocksStorageKey, state.burnClocks);
        }
        function loadStoredBurnClocks() {
            if (state.runner && state.runner.running) return;
            const stored = readLocalSetting(localStorage.getItem(burnClocksStorageKey));
            if (stored !== null) setBurnClocks(stored);
        }

        function renderAccountStrip(account) {
            state.account = account || null;
            if (!account) {
                els.accountStrip.style.display = 'none';
                els.accountStrip.innerHTML = '';
                return;
            }
            const tp = account.tp || {};
            const career = account.career;
            const careerHtml = career && career.active ? `
                <div id="career-pill" class="account-pill pill-career account-pill-clickable">
                    <span class="label">CAREER</span>
                    <strong>ONGOING</strong>
                </div>
            ` : `<div class="account-pill" style="opacity: 0.25;">
                    <span class="label">CAREER</span>
                    <strong>NONE</strong>
                </div>`;
            const carrots = account.carrots || {};
            els.accountStrip.innerHTML = `
                <div class="account-pill pill-tp">
                    <span class="label">TP</span>
                    <div class="pill-value-row">
                        <strong>${tp.current || 0}/${tp.max || 0}</strong>
                        <button id="pill-tp-refill" class="pill-btn pill-tp-refill" title="Refill TP">+</button>
                    </div>
                </div>
                <div class="account-pill pill-carrots">
                    <span class="label">CARROTS</span>
                    <strong>${formatNumber(carrots.total)}</strong>
                </div>
                <div class="account-pill pill-gold">
                    <span class="label">GOLD</span>
                    <strong>${formatNumber(account.gold)}</strong>
                </div>
                <div class="account-pill pill-clk">
                    <span class="label">CLOCKS</span>
                    <strong>${formatNumber(account.clocks)}</strong>
                </div>
                ${careerHtml}
                <button id="account-refresh-btn" class="pill-btn account-refresh-btn" title="Refresh account data">&#x21bb;</button>
            `;
            els.accountStrip.style.display = 'flex';
            const careerPill = document.getElementById('career-pill');
            if (careerPill) careerPill.addEventListener('click', openCareerModal);
            const refreshBtn = document.getElementById('account-refresh-btn');
            if (refreshBtn) {
                refreshBtn.addEventListener('click', async () => {
                    refreshBtn.disabled = true;
                    refreshBtn.textContent = '...';
                    try {
                        const data = await apiJson('/api/account/refresh', { method: 'POST' });
                        if (data.success && data.account) {
                            state.account = data.account;
                            if (dashData) {
                                dashData.account = data.account;
                                if (data.parents) {
                                    dashData.parents = data.parents;
                                    const selectedIds = new Set(selection.veterans.map(v => String(v.instance_id)));
                                    selection.veterans = dashData.parents
                                        .map((p, i) => selectedIds.has(String(p.instance_id)) ? { ...p, _gridIdx: i } : null)
                                        .filter(Boolean);
                                    renderParents(dashData.parents);
                                }
                            }
                            renderAccountStrip(state.account);
                        }
                    } catch (e) {
                        console.error('Refresh error:', e);
                    } finally {
                        const newBtn = document.getElementById('account-refresh-btn');
                        if (newBtn) { newBtn.disabled = false; newBtn.textContent = '\u21bb'; }
                    }
                });
            }
            const tpRefillBtn = document.getElementById('pill-tp-refill');
            if (tpRefillBtn) {
                tpRefillBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    tpRefillBtn.disabled = true;
                    tpRefillBtn.textContent = '...';
                    try {
                        const data = await apiJson('/api/tp/refill', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ count: 1 })
                        });
                        if (data.success) {
                            if (data.account) {
                                state.account = data.account;
                            } else {
                                const current = state.account && state.account.tp;
                                if (current) current.current = (data.tp || {}).current || current.current;
                            }
                            renderAccountStrip(state.account);
                        } else {
                            console.error('TP refill failed:', data.detail);
                        }
                    } catch (e) {
                        console.error('TP refill error:', e);
                    } finally {
                        const newBtn = document.getElementById('pill-tp-refill');
                        if (newBtn) { newBtn.disabled = false; newBtn.textContent = '+'; }
                    }
                });
            }
            loadStoredBurnClocks();
            syncBurnClocksControls();
        }

        els.burnClocksBtn.addEventListener('click', async () => {
            setBurnClocks(!state.burnClocks, { persist: true });
            if (state.runner && state.runner.running) {
                try {
                    const data = await apiJson('/api/career/runner/burn_clocks', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ burn_clocks: state.burnClocks })
                    });
                    if (!data.success) throw new Error(data.detail || 'Failed to update burn_clocks');
                    if (data.runner) applyRunnerSnapshot(data.runner);
                } catch (e) {
                    console.error("Failed to update burn_clocks mid-run", e);
                    if (state.runner && state.runner.burn_clocks !== undefined) {
                        setBurnClocks(state.runner.burn_clocks, { persist: true });
                    }
                }
            }
        });

        const rankMap = {
            1: 'G', 2: 'G+', 3: 'F', 4: 'F+', 5: 'E', 6: 'E+',
            7: 'D', 8: 'D+', 9: 'C', 10: 'C+', 11: 'B', 12: 'B+',
            13: 'A', 14: 'A+', 15: 'S', 16: 'S+', 17: 'SS', 18: 'SS+',
            19: 'UG', 20: 'UF', 21: 'UE', 22: 'UD'
        };
        let dashData = null;
        const selection = { deck: null, friend: null, trainee: null, veterans: [] };

        async function syncSelectionToServer() {
            selection.preset = state.selectedPreset || '';
            try {
                const payload = {
                    deck: selection.deck,
                    friend: selection.friend,
                    trainee: selection.trainee,
                    veterans: selection.veterans,
                    preset: state.selectedPreset || ''
                };
                await apiJson('/api/selection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ selection: payload })
                });
            } catch (e) {}
            saveSelectionToPreset();
        }

        async function saveSelectionToPreset() {
            if (!state.selectedPreset) return;
            const current = getCurrentPreset();
            if (!current) return;

            const team = {};
            if (selection.deck && selection.deck.id != null) team.deck = { id: selection.deck.id };
            if (selection.trainee && selection.trainee.id != null) team.trainee = { id: selection.trainee.id };
            const veterans = (selection.veterans || [])
                .filter(v => v && v.instance_id != null)
                .map(v => ({ instance_id: v.instance_id }));
            if (veterans.length) team.veterans = veterans;
            if (selection.friend && selection.friend.viewer_id != null) {
                team.friend = {
                    viewer_id: selection.friend.viewer_id,
                    support_card_id: selection.friend.support_card_id,
                };
            }
            current.team_selection = team;

            try {
                await apiJson('/api/presets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ preset: current })
                });
            } catch (e) {}
        }

        function applyPresetTeamSelection() {
            const activeCareer = state.account && state.account.career && state.account.career.active;
            if (activeCareer) return;
            const current = getCurrentPreset();
            if (!current || !current.team_selection) return;

            resetSelection();
            document.querySelectorAll('.deck-container.selected, #uma-grid .grid-card.selected, #parent-grid .grid-card.selected, #friend-grid .grid-card.selected')
                .forEach(el => el.classList.remove('selected'));

            applyServerSelection(current.team_selection);
            selection.preset = state.selectedPreset || '';
            syncSelectionToServer();
            renderFriends();
            renderTeamPanel();
        }

        function deselect(action, idx) {
            if (action === 'deck') {
                document.querySelectorAll('.deck-container.selected').forEach(el => el.classList.remove('selected'));
                selection.deck = null;
            } else if (action === 'friend') {
                document.querySelectorAll('#friend-grid .grid-card.selected').forEach(el => el.classList.remove('selected'));
                selection.friend = null;
            } else if (action === 'trainee') {
                document.querySelectorAll('#uma-grid .grid-card.selected').forEach(el => el.classList.remove('selected'));
                selection.trainee = null;
            } else if (action === 'vet') {
                const vet = selection.veterans[idx];
                if (vet != null) {
                    const card = document.querySelector(`#parent-grid .grid-card[data-pidx="${vet._gridIdx}"]`);
                    if (card) card.classList.remove('selected');
                }
                selection.veterans.splice(idx, 1);
                updateVetSelectability();
            }
            renderTeamPanel();
            syncSelectionToServer();
        }
        function getStartMissingReason() {
            const activeCareer = state.account && state.account.career && state.account.career.active;
            if (!state.selectedPreset) return 'Select a preset';
            if (activeCareer) return '';
            if (!selection.deck) return 'Select a deck';
            if (!selection.friend) return 'Select a friend support';
            if (!selection.trainee) return 'Select a trainee';
            if (selection.veterans.length < 2) return 'Select two parents';
            const parentError = getParentSelectionError();
            if (parentError) return parentError;
            const tp = state.account && state.account.tp ? Number(state.account.tp.current || 0) : 0;
            if (state.account && tp < 30 && !state.devEnabled) return `Not enough TP: ${tp}/30`;
            return '';
        }
        function getParentLineageCards(parent) {
            if (!parent || !parent.tree) return [];
            return ['self', 'p1', 'p2', 'gp1', 'gp2', 'gp3', 'gp4']
                .map(key => Number(parent.tree[key] && parent.tree[key].card_id))
                .filter(Boolean);
        }
        function getParentSelectionError() {
            if (!selection.trainee) return '';
            const traineeId = Number(selection.trainee.id);
            const lineages = selection.veterans.map(getParentLineageCards);
            if (lineages.length < 2) return '';
            if (lineages.some(cards => cards[0] === traineeId)) return 'Direct parent is trainee';
            return '';
        }
        function syncStartButton() {
            const reason = getStartMissingReason();
            els.startCareerBtn.disabled = Boolean(reason) || state.isStartingCareer;
            if (state.isStartingCareer) {
                els.startCareerBtn.innerText = 'RUNNING...';
                els.startStatus.innerText = 'Starting runner...';
                els.startStatus.classList.remove('error');
            } else {
                const activeCareer = state.account && state.account.career && state.account.career.active;
                els.startCareerBtn.innerText = activeCareer ? 'RESUME CAREER' : 'RUN CAREER';
                els.startStatus.innerText = reason;
                els.startStatus.classList.toggle('error', false);
            }
        }
        function renderTeamPanel() {
            document.getElementById('dashboard-view').classList.add('active');
            function setSlot(id, role, content, action, idx, emptyText = 'select') {
                const el = document.getElementById(id);
                el.className = content ? 'team-item filled' : 'team-item';
                el.onclick = content ? () => deselect(action, idx) : null;
                const clear = content ? '<span class="team-item-clear">clear</span>' : '';
                const empty = `<div class="team-item-empty">${emptyText}</div>`;
                el.innerHTML = `
                    <div class="team-item-head">
                        <span class="team-item-role">${role}</span>
                        ${clear}
                    </div>
                    ${content || empty}
                `;
            }
            if (selection.deck) {
                const thumbs = selection.deck.cards.map(c =>
                    `<img class="team-item-thumb" src="/api/images/${c.id || '10001'}.png" onerror="hideBrokenImage(this)">`
                ).join('');
                setSlot('team-slot-deck', 'Deck', `
                    <div class="team-item-body">
                        <div class="team-item-thumbs">${thumbs}</div>
                        <div class="team-item-text">
                            <span class="team-item-name">${selection.deck.name}</span>
                            <span class="team-item-sub">Slot ${selection.deck.id}</span>
                        </div>
                    </div>
                `, 'deck', null, 'select deck');
            } else {
                setSlot('team-slot-deck', 'Deck', null, 'deck', null, 'select deck');
            }
            if (selection.friend) {
                setSlot('team-slot-friend', 'Friend', `
                    <div class="team-item-body">
                        <img class="team-item-portrait" src="/api/images/${selection.friend.support_card_id || '10001'}.png" onerror="hideBrokenImage(this)">
                        <div class="team-item-text">
                            <span class="team-item-name">${selection.friend.support_name || 'Unknown'}</span>
                            <span class="team-item-sub">${selection.friend.type || '?'} | LB${selection.friend.limit_break_count ?? '?'}</span>
                        </div>
                    </div>
                `, 'friend', null, 'select friend');
            } else {
                setSlot('team-slot-friend', 'Friend', null, 'friend', null, 'select friend');
            }
            if (selection.trainee) {
                setSlot('team-slot-trainee', 'Trainee', `
                    <div class="team-item-body">
                        <img class="team-item-portrait" src="/api/images/${selection.trainee.id || '100101'}.png" onerror="hideBrokenImage(this)">
                        <div class="team-item-text">
                            <span class="team-item-name">${selection.trainee.name || 'Unknown'}</span>
                        </div>
                    </div>
                `, 'trainee', null, 'select trainee');
            } else {
                setSlot('team-slot-trainee', 'Trainee', null, 'trainee', null, 'select trainee');
            }
            ['team-slot-vet1', 'team-slot-vet2'].forEach((id, i) => {
                const vet = selection.veterans[i];
                if (vet) {
                    setSlot(id, `Parent ${i + 1}`, `
                        <div class="team-item-body">
                            <img class="team-item-portrait" src="/api/images/${vet.card_id || '100101'}.png" onerror="hideBrokenImage(this)">
                            <div class="team-item-text">
                                <span class="team-item-name">${vet.name || 'Unknown'}</span>
                                <span class="team-item-sub">${rankMap[vet.rank] || '??'}</span>
                            </div>
                        </div>
                    `, 'vet', i, 'select parent');
                } else {
                    setSlot(id, `Parent ${i + 1}`, null, 'vet', i, 'select parent');
                }
            });
            syncStartButton();
            updateAptitudePreview();
        }
                function updateVetSelectability() {
            const full = selection.veterans.length >= 2;
            document.querySelectorAll('#parent-grid .grid-card').forEach(card => {
                if (card.classList.contains('selected')) {
                    card.classList.remove('vet-full');
                } else {
                    card.classList.toggle('vet-full', full);
                }
            });
            syncStartButton();
        }
        function clampValue(value, min, max) {
            return Math.min(Math.max(value, min), max);
        }
        let activeSparkCard = null;
        let activeSparkTooltip = null;
        function positionSparkTooltip(card, tooltip = card.querySelector('.sparks-tooltip')) {
            if (!card || !tooltip) return;
            const rect = card.getBoundingClientRect();
            const tooltipRect = tooltip.getBoundingClientRect();
            const tooltipWidth = Math.min(tooltipRect.width || 620, window.innerWidth - 16);
            const tooltipHeight = tooltipRect.height || 320;
            const x = clampValue(rect.left + rect.width / 2, tooltipWidth / 2 + 8, window.innerWidth - tooltipWidth / 2 - 8);
            const y = Math.max(8, rect.top - tooltipHeight - 10);
            tooltip.style.setProperty('--tooltip-left', `${x}px`);
            tooltip.style.setProperty('--tooltip-top', `${y}px`);
        }
        function bindSparkTooltips() {
            document.querySelectorAll('body > .sparks-tooltip').forEach(tooltip => tooltip.remove());
            document.querySelectorAll('#parent-grid .grid-card').forEach(card => {
                const tooltip = card.querySelector('.sparks-tooltip');
                if (!tooltip) return;
                card.classList.add('has-sparks');
                let hideTimer = null;
                const show = () => {
                    clearTimeout(hideTimer);
                    if (tooltip.parentElement !== document.body) document.body.appendChild(tooltip);
                    activeSparkCard = card;
                    activeSparkTooltip = tooltip;
                    positionSparkTooltip(card, tooltip);
                    tooltip.classList.add('is-visible');
                };
                const scheduleHide = () => {
                    clearTimeout(hideTimer);
                    hideTimer = window.setTimeout(() => {
                        if (activeSparkCard === card) {
                            activeSparkCard = null;
                            activeSparkTooltip = null;
                        }
                        tooltip.classList.remove('is-visible');
                    }, 200);
                };
                tooltip.addEventListener('click', event => event.stopPropagation());
                tooltip.addEventListener('mousedown', event => event.stopPropagation());
                tooltip.addEventListener('mouseenter', show);
                tooltip.addEventListener('mouseleave', scheduleHide);
                card.addEventListener('mouseenter', show);
                card.addEventListener('mouseleave', scheduleHide);
                card.addEventListener('focusin', show);
                card.addEventListener('focusout', scheduleHide);
            });
        }
        document.addEventListener('scroll', () => {
            if (activeSparkCard && activeSparkTooltip) positionSparkTooltip(activeSparkCard, activeSparkTooltip);
        }, true);
        window.addEventListener('resize', () => {
            if (activeSparkCard && activeSparkTooltip) positionSparkTooltip(activeSparkCard, activeSparkTooltip);
        });
        function friendKey(friend) {
            return `${friend.viewer_id}:${friend.support_card_id}`;
        }
        function normalizedCardName(value) {
            return String(value || '').toLowerCase().replace(/\([^)]*\)/g, '').replace(/[^a-z0-9]+/g, '');
        }
        function friendAllowed(friend) {
            if (!friend) return false;
            const friendId = String(friend.support_card_id || '');
            const friendName = normalizedCardName(friend.support_name);
            if (selection.deck) {
                const deckIds = new Set(selection.deck.cards.map(card => String(card.id || '')));
                if (deckIds.has(friendId)) return false;
                const deckNames = new Set(selection.deck.cards.map(card => normalizedCardName(card.name)));
                if (friendName && deckNames.has(friendName)) return false;
            }
            if (selection.trainee && friendName && normalizedCardName(selection.trainee.name) === friendName) return false;
            return true;
        }
        function getVisibleFriends() {
            const friends = (dashData && dashData.friends) || [];
            const typeFilter = (state.friendTypeFilter || '').toLowerCase();
            return friends.filter(f => {
                if (!friendAllowed(f)) return false;
                if (typeFilter && (f.type || '').toLowerCase() !== typeFilter) return false;
                return true;
            });
        }
        function clearInvalidFriendSelection() {
            if (selection.friend && !friendAllowed(selection.friend)) {
                selection.friend = null;
            }
        }
        function syncFriendSelection() {
            const visibleFriends = (dashData && dashData.visibleFriends) || [];
            document.querySelectorAll('#friend-grid .grid-card').forEach((el, i) => {
                const friend = visibleFriends[i];
                el.classList.toggle('selected', Boolean(selection.friend && friend && friendKey(selection.friend) === friendKey(friend)));
            });
        }
        function findDeckIndexForCareer(activeCareer) {
            const decks = (dashData && dashData.validDecks) || [];
            if (!activeCareer || !decks.length) return -1;
            if (activeCareer.deck_id) {
                const deckIdx = decks.findIndex(d => Number(d.id) === Number(activeCareer.deck_id));
                if (deckIdx >= 0) return deckIdx;
            }
            const supportIds = (activeCareer.support_card_ids || []).map(id => String(id)).filter(Boolean);
            if (!supportIds.length) return -1;
            const careerSet = new Set(supportIds);
            return decks.findIndex(deck => {
                const deckIds = (deck.cards || []).map(card => String(card.id || '')).filter(Boolean);
                return deckIds.length === careerSet.size && deckIds.every(id => careerSet.has(id));
            });
        }
        function selectCareerDeck(activeCareer) {
            const deckIdx = findDeckIndexForCareer(activeCareer);
            if (deckIdx >= 0) {
                selection.deck = dashData.validDecks[deckIdx];
                const deckEls = document.querySelectorAll('.deck-container');
                if (deckEls[deckIdx]) deckEls[deckIdx].classList.add('selected');
                return;
            }
            const supportCards = (activeCareer && activeCareer.support_cards) || [];
            if (supportCards.length) {
                selection.deck = {
                    id: activeCareer.deck_id || 'active',
                    name: activeCareer.deck_id ? `Deck ${activeCareer.deck_id}` : 'Active career deck',
                    cards: supportCards
                };
            }
        }
        function selectCareerFriend(activeCareer) {
            if (!activeCareer || !activeCareer.friend_viewer_id || !activeCareer.friend_card_id) return;
            state.pendingFriendSelection = {
                viewer_id: String(activeCareer.friend_viewer_id),
                support_card_id: String(activeCareer.friend_card_id)
            };
            if (activeCareer.friend) {
                selection.friend = {
                    ...activeCareer.friend,
                    viewer_id: String(activeCareer.friend_viewer_id),
                    support_card_id: String(activeCareer.friend_card_id)
                };
            }
        }
        async function loadRaceData() {
            try {
                const raceRes = await fetch('/assets/data/uma_race_data.json');
                const data = await raceRes.json();
                state.raceData = Array.isArray(data.races) ? data.races : [];
                syncSelectedPresetRaces();
                renderTrackblazer();
                renderRaces();
            } catch (e) {}
        }

        function getCurrentPreset() {
            return (state.presets || []).find(p => p.name === state.selectedPreset);
        }

        function normalizePresetName(value) {
            return String(value || '').trim().replace(/[^a-zA-Z0-9._ -]+/g, '').replace(/\s+/g, ' ').trim();
        }

        function presetNameExists(name) {
            const normalized = normalizePresetName(name).toLowerCase();
            return Boolean(normalized && (state.presets || []).some(p => p.name.toLowerCase() === normalized));
        }

        function syncSelectedPresetRaces() {
            const current = getCurrentPreset();
            state.selectedRaces = (current?.extra_race_list || [])
                .map(id => parseInt(id, 10))
                .filter(id => Number.isFinite(id));
            state.mandatoryRaces = (current?.mandatory_race_list || [])
                .map(id => parseInt(id, 10))
                .filter(id => Number.isFinite(id));
        }

        function renderTrackblazer(preset) {
            const panel = document.getElementById('trackblazer-panel');
            const statsEl = document.getElementById('trackblazer-stats');
            const hintEl = document.getElementById('trackblazer-hint');
            const epEl = document.getElementById('trackblazer-epithets');
            if (!panel || !statsEl || !hintEl || !epEl) return;

            const src = preset || getCurrentPreset();
            const tb = src?.trackblazer;

            if (!tb) {
                panel.style.display = 'none';
                return;
            }

            statsEl.textContent = `+${tb.stat_bonus} Stats`;
            hintEl.textContent = `${tb.skill_hint} Hint`;
            epEl.innerHTML = (tb.epithets || []).map(e =>
                `<span class="trackblazer-epithet-tag">${escapeHtml(e)}</span>`
            ).join('');
            panel.style.display = 'flex';
        }

        function populateTrackblazerSelect() {
            const sel = document.getElementById('trackblazer-schedule-select');
            if (!sel) return;
            // Keep the — None — option, remove others
            while (sel.options.length > 1) sel.remove(1);
            if (!state.presets) return;
            let added = 0;
            for (const p of state.presets) {
                if (!p.trackblazer) continue;
                const opt = document.createElement('option');
                opt.value = p.name;
                opt.textContent = `${p.name}  (+${p.trackblazer.stat_bonus} Stats · ${p.trackblazer.skill_hint})`;
                sel.appendChild(opt);
                added++;
            }
            // Auto-select if the current preset has trackblazer data
            const current = getCurrentPreset();
            sel.value = (current?.trackblazer) ? current.name : '';
        }

        function bindTrackblazerSchedule() {
            const sel = document.getElementById('trackblazer-schedule-select');
            if (!sel) return;
            sel.addEventListener('change', function() {
                const name = this.value;
                if (!name || !state.presets) {
                    // Clear trackblazer panel and races when "-- None --" selected
                    renderTrackblazer(null);
                    state.selectedRaces = [];
                    renderRaces();
                    autoSaveRaces();
                    return;
                }
                const preset = state.presets.find(p => p.name === name);
                if (!preset || !preset.extra_race_list) return;

                // Fill race schedule
                state.selectedRaces = preset.extra_race_list
                    .map(id => parseInt(id, 10))
                    .filter(id => Number.isFinite(id));

                renderTrackblazer(preset);
                renderRaces();
                autoSaveRaces();
            });
        }

        function getYearSlots(yearIdx) {
            const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            const periods = ['Early', 'Late'];
            const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
            const slots = [];
            for (const month of months) {
                for (const period of periods) {
                    const label = period + ' ' + month;
                    const datePrefix = yearLabels[yearIdx] + ' ' + label;
                    const races = state.raceData.filter(r => r.date.includes(datePrefix));
                    slots.push({ period: label, races: races, yearIdx: yearIdx });
                }
            }
            return slots;
        }

        function raceKeys(race) {
            const keys = [race.id, ...(race.legacy_ids || [])];
            return keys.map(id => parseInt(id)).filter(id => Number.isFinite(id));
        }

        function raceSelected(race) {
            return raceKeys(race).some(id => state.selectedRaces.includes(id));
        }

        function renderRaces() {
            if (!els.raceOptionsContent) return;
            els.raceOptionsContent.innerHTML = '';

            const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
            yearLabels.forEach((label, yi) => {
                const block = document.createElement('div');
                block.className = 'race-year-block';
                block.innerHTML = `<div class="race-year-title">${label}</div>`;

                const grid = document.createElement('div');
                grid.className = 'race-time-grid';

                const slots = getYearSlots(yi);
                slots.forEach((slot, si) => {
                    const cell = document.createElement('div');
                    cell.className = 'race-time-cell';

                    const slotIds = slot.races.flatMap(r => raceKeys(r));
                    const selectedInSlot = state.selectedRaces.filter(id => slotIds.includes(id));
                    const mainRaceId = selectedInSlot[0];
                    const selected = slot.races.find(r => raceKeys(r).includes(mainRaceId));

                    let html = `<div class="race-time-label">${slot.period}</div>`;
                    if (selected) {
                        const mandatory = state.mandatoryRaces?.includes(mainRaceId);
                        html += `
                            <div class="race-cell-selected-img">
                                <img src="/races/${encodeURIComponent(selected.name)}.png" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'">
                                <div class="race-image-fallback" style="display:none">${selected.type}</div>
                                <span class="race-cell-selected-grade badge-${selected.type.toLowerCase().replace('-', '')}">${selected.type}</span>
                            </div>
                            <div class="race-cell-selected-name">${escapeHtml(selected.name)}</div>
                            <div class="race-cell-selected-mode">${mandatory ? 'MANDATORY' : 'OPTIONAL'}</div>
                        `;
                    } else {
                        html += `<div class="race-time-plus">+</div>`;
                    }

                    cell.innerHTML = html;
                    cell.onclick = () => openSlotPopup(slot, yi);
                    grid.appendChild(cell);
                });

                block.appendChild(grid);
                els.raceOptionsContent.appendChild(block);
            });
        }

        function openSlotPopup(slot, yearIdx) {
            const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
            els.racePopupTitle.textContent = `${yearLabels[yearIdx]} - ${slot.period}`;
            els.racePopupBody.innerHTML = '';

            if (slot.races.length === 0) {
                els.racePopupBody.innerHTML = '<div class="race-slot-popup-empty">No races available</div>';
            } else {
                const list = document.createElement('div');
                list.className = 'race-slot-popup-list';

                const slotIds = slot.races.flatMap(r => raceKeys(r));

                slot.races.forEach(race => {
                    const myIds = raceKeys(race);
                    const selectedInSlot = state.selectedRaces.filter(id => slotIds.includes(id));
                    const selIndex = selectedInSlot.findIndex(id => myIds.includes(id));
                    const isSelected = selIndex !== -1;
                    const isMandatory = myIds.some(id => state.mandatoryRaces?.includes(id));

                    let badgeHtml = isMandatory ? '<div class="race-slot-popup-check main-race" style="font-size: 0.7rem; font-weight: bold; width: auto; padding: 0 8px; border-radius: 12px; background: rgba(255,255,255,0.25);">MANDATORY</div>' : '<div class="race-slot-popup-check">OPTIONAL</div>';
                    if (isSelected && state.scenarioType === "Mant" && selectedInSlot.length > 0) {
                        if (selIndex === 0) {
                            badgeHtml = '<div class="race-slot-popup-check main-race" style="font-size: 0.7rem; font-weight: bold; width: auto; padding: 0 8px; border-radius: 12px; background: rgba(255,255,255,0.2);">MAIN</div>';
                        } else {
                            badgeHtml = `<div class="race-slot-popup-check overwrite-race" style="font-size: 0.7rem; font-weight: bold; width: auto; padding: 0 8px; border-radius: 12px; background: rgba(255,255,255,0.1);">RIVAL OVERWRITE ${selIndex}</div>`;
                        }
                    }

                    const item = document.createElement('div');
                    item.className = `race-slot-popup-item ${isSelected ? 'on' : ''}`;
                    item.innerHTML = `
                        <div class="race-slot-popup-img">
                            <img src="/races/${encodeURIComponent(race.name)}.png" onerror="this.src='/broom.png'">
                        </div>
                        <div class="race-slot-popup-info">
                            <div class="race-slot-popup-name-row">
                                <span class="race-slot-popup-grade badge-${race.type.toLowerCase().replace('-', '')}">${race.type}</span>
                                <span class="race-slot-popup-name">${escapeHtml(race.name)}</span>
                            </div>
                            <div class="race-slot-popup-meta">
                                <span class="race-slot-popup-terrain ${race.terrain.toLowerCase()}">${race.terrain}</span>
                                <span class="race-slot-popup-distance">${race.distance}</span>
                            </div>
                        </div>
                        ${badgeHtml}
                    `;
                    item.onclick = async () => {
                        const isMant = state.scenarioType === "Mant";

                        if (isSelected) {
                            if (isMandatory) {
                                state.mandatoryRaces = (state.mandatoryRaces || []).filter(id => !myIds.includes(id));
                            } else {
                                state.selectedRaces = state.selectedRaces.filter(id => !myIds.includes(id));
                                state.mandatoryRaces = (state.mandatoryRaces || []).filter(id => !myIds.includes(id));
                            }
                        } else {
                            if (!isMant) {
                                state.selectedRaces = state.selectedRaces.filter(id => !slotIds.includes(id));
                                state.mandatoryRaces = (state.mandatoryRaces || []).filter(id => !slotIds.includes(id));
                            }
                            state.selectedRaces.push(parseInt(race.id));
                        }

                        openSlotPopup(slot, yearIdx);
                        renderRaces();
                        await autoSaveRaces();
                    };
                    item.oncontextmenu = async (e) => {
                        e.preventDefault();
                        if (!isSelected) return;
                        const id = parseInt(race.id);
                        state.mandatoryRaces = isMandatory
                            ? (state.mandatoryRaces || []).filter(x => !myIds.includes(x))
                            : [...(state.mandatoryRaces || []).filter(x => !slotIds.includes(x)), id];
                        openSlotPopup(slot, yearIdx);
                        renderRaces();
                        await autoSaveRaces();
                    };
                    list.appendChild(item);
                });
                els.racePopupBody.appendChild(list);
            }
            els.racePopupOverlay.style.display = 'flex';
        }

        async function autoSaveRaces() {
            try {
                const current = getCurrentPreset();
                if (current) {
                    current.extra_race_list = [...state.selectedRaces];
                    current.mandatory_race_list = [...(state.mandatoryRaces || [])];
                }
                await apiJson('/api/presets/save_races', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: state.selectedPreset,
                        races: state.selectedRaces,
                        mandatory_races: state.mandatoryRaces || []
                    })
                });
            } catch (e) {}
        }

        function getTurnFromDate(dateStr) {
            const match = dateStr.match(/(\d+)年(\d+)月(前|後)半/);
            if (!match) return 0;
            const year = parseInt(match[1]);
            const month = parseInt(match[2]);
            const half = match[3] === '前' ? 0 : 1;
            return (year - 1) * 24 + (month - 1) * 2 + half + 1;
        }

        function bindRaceHandlers() {
            els.racePopupClose?.addEventListener('click', () => {
                els.racePopupOverlay.style.display = 'none';
            });
            els.racePopupOverlay?.addEventListener('click', (e) => {
                if (e.target === els.racePopupOverlay) els.racePopupOverlay.style.display = 'none';
            });

            makeSectionToggle('race-toggle', 'race-chevron', 'race-body', false);
        }

        let skillDataCache = null;
        let activeEditTier = null;
        let activeSkillFilter = null;
        let activeColorFilter = null;

        const SKILL_FILTERS = [
            { id: 101, label: 'Front' },
            { id: 102, label: 'Pace' },
            { id: 103, label: 'Late' },
            { id: 104, label: 'End' },
            { id: 201, label: 'Short' },
            { id: 202, label: 'Mile' },
            { id: 203, label: 'Medium' },
            { id: 204, label: 'Long' },
            { id: 502, label: 'Dirt' },
            { id: 'turf', label: 'Turf' }
        ];

        const COLOR_FILTERS = [
            { id: 'green', label: 'Green', color: '#4ade80', iconPrefixes: ['1001', '1002', '1003', '1004', '1005', '1006'] },
            { id: 'blue', label: 'Blue', color: '#60a5fa', iconPrefixes: ['2002'] },
            { id: 'yellow', label: 'Yellow', color: '#fbbf24', iconPrefixes: ['2001', '2004', '2005', '2006', '2009'] },
            { id: 'red', label: 'Red', color: '#f87171', iconPrefixes: ['3001', '3002', '3004', '3005', '3007'] }
        ];

        async function loadSkillData() {
            if (skillDataCache) return skillDataCache;
            try {
                const res = await apiJson('/api/skills');
                if (res.success && res.skills) {
                    const uniqueMap = new Map();
                    Object.entries(res.skills).forEach(([id, s]) => {
                        if (!uniqueMap.has(s.name)) {
                            uniqueMap.set(s.name, { id, ...s, tags: new Set(s.tags || []) });
                        } else {
                            const existing = uniqueMap.get(s.name);
                            if (s.rarity > existing.rarity) existing.rarity = s.rarity;
                            (s.tags || []).forEach(t => existing.tags.add(t));
                        }
                    });
                    skillDataCache = Array.from(uniqueMap.values()).map(s => ({ ...s, tags: Array.from(s.tags) }));
                    skillDataCache.sort((a, b) => a.name.localeCompare(b.name));
                    return skillDataCache;
                }
            } catch (e) {}
            return [];
        }

        function renderSkillFilters() {
            const container = document.getElementById('skill-filters');
            if (!container) return;
            
            let html = '<div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 4px;">';
            for (const filter of SKILL_FILTERS) {
                const isActive = activeSkillFilter === filter.id;
                const bg = isActive ? 'rgba(var(--accent-primary-rgb), 0.2)' : 'rgba(255,255,255,0.05)';
                const border = isActive ? 'var(--accent-primary)' : 'transparent';
                const color = isActive ? 'var(--text-main)' : '#a1a1aa';
                html += `<div class="skill-filter-chip affinity-filter" data-id="${filter.id}" style="padding: 0.35rem 0.75rem; border-radius: 1rem; font-size: 0.75rem; cursor: pointer; background: ${bg}; border: 1px solid ${border}; color: ${color}; font-weight: bold; transition: all 0.1s;">${filter.label}</div>`;
            }
            html += '</div><div style="display: flex; flex-wrap: wrap; gap: 4px;">';
            
            for (const filter of COLOR_FILTERS) {
                const isActive = activeColorFilter === filter.id;
                const bg = isActive ? `${filter.color}33` : 'rgba(255,255,255,0.05)';
                const border = isActive ? filter.color : 'transparent';
                const color = isActive ? 'var(--text-main)' : filter.color;
                html += `<div class="skill-filter-chip color-filter" data-color="${filter.id}" style="padding: 0.35rem 0.75rem; border-radius: 1rem; font-size: 0.75rem; cursor: pointer; background: ${bg}; border: 1px solid ${border}; color: ${color}; font-weight: bold; transition: all 0.1s;">${filter.label}</div>`;
            }
            html += '</div>';
            
            container.innerHTML = html;
            
            container.querySelectorAll('.affinity-filter').forEach(el => {
                el.addEventListener('click', () => {
                    let tagId = el.getAttribute('data-id');
                    if (tagId !== 'turf') tagId = Number(tagId);
                    
                    if (activeSkillFilter === tagId) activeSkillFilter = null;
                    else activeSkillFilter = tagId;
                    
                    renderSkillFilters();
                    renderSkillList();
                });
            });

            container.querySelectorAll('.color-filter').forEach(el => {
                el.addEventListener('click', () => {
                    const colorId = el.getAttribute('data-color');
                    
                    if (activeColorFilter === colorId) activeColorFilter = null;
                    else activeColorFilter = colorId;
                    
                    renderSkillFilters();
                    renderSkillList();
                });
            });
        }

        function renderSkillList() {
            const query = (els.skillSearch?.value || '').toLowerCase();
            const skills = skillDataCache || [];
            
            let count = 0;
            let html = '';
            for (const s of skills) {
                if (query && !s.name.toLowerCase().includes(query)) continue;
                
                if (activeSkillFilter !== null) {
                    const skillTags = s.tags || [];
                    if (activeSkillFilter === 'turf') {
                        if (skillTags.includes(502)) continue;
                    } else {
                        if (!skillTags.includes(activeSkillFilter)) continue;
                    }
                }
                
                if (activeColorFilter !== null) {
                    const iconId = String(s.icon_id || '');
                    const colorFilter = COLOR_FILTERS.find(filter => filter.id === activeColorFilter);
                    const skillColor = colorFilter && colorFilter.iconPrefixes.some(prefix => iconId.startsWith(prefix)) ? activeColorFilter : 'none';
                    
                    if (skillColor !== activeColorFilter) continue;
                }
                
                count++;
                
                html += `<div class="skill-list-item" data-name="${escapeAttr(s.name)}" style="padding: 0.5rem; background: rgba(255,255,255,0.03); border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: background 0.1s;">
                    <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-main); font-size: 0.85rem;">${escapeHtml(s.name)}</span>
                </div>`;
            }
            
            if (els.skillList) {
                if (count === 0) {
                    els.skillList.innerHTML = `<div style="padding: 1rem; color: #a1a1aa; font-size: 0.85rem;">No skills found.</div>`;
                } else {
                    els.skillList.innerHTML = html;
                    els.skillList.querySelectorAll('.skill-list-item').forEach(el => {
                        el.addEventListener('click', () => {
                            const name = el.getAttribute('data-name');
                            addSkillToFocusedArea(name);
                        });
                        el.addEventListener('mouseenter', () => el.style.background = 'rgba(255,255,255,0.1)');
                        el.addEventListener('mouseleave', () => el.style.background = 'rgba(255,255,255,0.03)');
                    });
                }
            }
        }

        function renderSkillEditorRightSide() {
            const current = getCurrentPreset();
            if (!current) {
                if (els.skillTiersContainer) els.skillTiersContainer.innerHTML = '';
                if (els.skillBlacklistContainer) els.skillBlacklistContainer.innerHTML = '';
                return;
            }

            let tiersHtml = '';
            const storedTiers = current.learn_skill_list || [];
            const tiers = storedTiers.length > 0 ? storedTiers : [[]];
            tiers.forEach((tier, i) => {
                const isActive = activeEditTier === i;
                const itemsHtml = tier.map(s =>
                    `<div class="skill-tag">
                        ${escapeHtml(s)} <span class="skill-tag-del" data-tier="${i}" data-skill="${escapeAttr(s)}">&times;</span>
                    </div>`
                ).join('');

                tiersHtml += `
                <div class="skill-tier-dropzone ${isActive ? 'is-active' : ''}" data-tier="${i}">
                    <div class="skill-tier-header">
                        <span class="skill-tier-label">TIER ${i+1}</span>
                        <button class="btn btn-sm btn-danger-soft skill-editor-action tier-del-btn" data-tier="${i}">DEL</button>
                    </div>
                    <div class="skill-tag-list">
                        ${itemsHtml}
                    </div>
                </div>`;
            });
            if (els.skillTiersContainer) els.skillTiersContainer.innerHTML = tiersHtml;

            if (els.skillBlacklistContainer) {
                const isBlActive = activeEditTier === null;
                els.skillBlacklistContainer.classList.toggle('is-active', isBlActive);

                const blacklist = current.learn_skill_blacklist || [];
                els.skillBlacklistContainer.innerHTML = blacklist.map(s =>
                    `<div class="skill-tag blacklist">
                        ${escapeHtml(s)} <span class="skill-tag-del" data-blacklist="true" data-skill="${escapeAttr(s)}">&times;</span>
                    </div>`
                ).join('');
            }

            els.skillTiersContainer?.querySelectorAll('.skill-tier-dropzone').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.classList.contains('tier-del-btn') || e.target.classList.contains('skill-tag-del')) return;
                    activeEditTier = parseInt(el.getAttribute('data-tier'));
                    renderSkillEditorRightSide();
                });
            });
            if (els.skillBlacklistContainer) {
                els.skillBlacklistContainer.onclick = (e) => {
                    if (e.target.classList.contains('skill-tag-del')) return;
                    activeEditTier = null;
                    renderSkillEditorRightSide();
                };
            }

            els.skillTiersContainer?.querySelectorAll('.tier-del-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const idx = parseInt(btn.getAttribute('data-tier'));
                    current.learn_skill_list = current.learn_skill_list || [];
                    current.learn_skill_list.splice(idx, 1);
                    if (activeEditTier === idx) activeEditTier = null;
                    else if (activeEditTier > idx) activeEditTier--;
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                });
            });

            document.querySelectorAll('.skill-tag-del').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const skillName = btn.getAttribute('data-skill');
                    if (btn.hasAttribute('data-blacklist')) {
                        current.learn_skill_blacklist = current.learn_skill_blacklist.filter(s => s !== skillName);
                    } else {
                        const tierIdx = parseInt(btn.getAttribute('data-tier'));
                        current.learn_skill_list[tierIdx] = current.learn_skill_list[tierIdx].filter(s => s !== skillName);
                    }
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                });
            });
        }

        async function addSkillToFocusedArea(name) {
            const current = getCurrentPreset();
            if (!current) return;

            if (activeEditTier === null) {
                if (!current.learn_skill_blacklist) current.learn_skill_blacklist = [];
                if (!current.learn_skill_blacklist.includes(name)) {
                    current.learn_skill_blacklist.push(name);
                }
            } else {
                if (!current.learn_skill_list) current.learn_skill_list = [];
                if (!current.learn_skill_list[activeEditTier]) current.learn_skill_list[activeEditTier] = [];
                if (!current.learn_skill_list[activeEditTier].includes(name)) {
                    current.learn_skill_list[activeEditTier].push(name);
                }
            }
            await savePresetConfig();
            renderSkillEditorRightSide();
        }

        function initSkillEditor() {
            if (!state.selectedPreset) return;
            activeEditTier = 0;

            els.skillModal.style.display = 'flex';
            if (els.skillSearch) els.skillSearch.value = '';
            activeSkillFilter = null;
            activeColorFilter = null;

            loadSkillData().then(() => {
                renderSkillFilters();
                renderSkillList();
            });
            renderSkillEditorRightSide();
        }

        async function savePresetConfig() {
            if (!state.selectedPreset || !state.presets) return;
            const current = getCurrentPreset();
            if (!current) return;

            current.learn_skill_threshold = parseInt(els.presetSkillThreshold.value) || 888;
            current.running_style = parseInt(els.presetRunningStyle?.value) || 1;
            current.scenario_id = parseInt(els.presetScenario?.value) || 4;
            current.scenario = current.scenario_id;
            state.scenarioType = scenarioTypes[current.scenario_id] || "Mant";
            current.unity_config = current.unity_config || {};
            const unityTrainingWeight = parseFloat(els.unityTrainingWeight?.value);
            const unityBurstWeight = parseFloat(els.unityBurstWeight?.value);
            current.unity_config.unity_training_weight = Number.isFinite(unityTrainingWeight) ? unityTrainingWeight : 0.6;
            current.unity_config.spirit_burst_weight = Number.isFinite(unityBurstWeight) ? unityBurstWeight : 5.0;
            current.unity_config.default_distance_type = parseInt(current.unity_config.default_distance_type) || 1;
            current.unity_config.default_running_style = parseInt(current.running_style) || 1;
            current.run_delay_min_min = parseInt(els.presetDelayMin?.value) || 0;
            current.run_delay_max_min = parseInt(els.presetDelayMax?.value) || 0;
            current.tp_mode = (els.presetTpMode?.value === 'wait') ? 'wait' : 'carat';
            current.use_mcts = !!(els.presetUseMcts?.checked);
            current.pal_recreation_required = !!(els.presetPalRecreation?.checked);
            current.parent_run = !!(els.presetParentRun?.checked);

            // Expect attribute: [speed, stamina, power, guts, wit]
            const speed = parseInt(els.presetExpectSpeed?.value);
            const stamina = parseInt(els.presetExpectStamina?.value);
            const power = parseInt(els.presetExpectPower?.value);
            const guts = parseInt(els.presetExpectGuts?.value);
            const wit = parseInt(els.presetExpectWit?.value);
            const attr = [speed, stamina, power, guts, wit];
            if (attr.some(v => Number.isFinite(v))) {
                current.expect_attribute = attr.map(v => Number.isFinite(v) ? v : 0);
            } else {
                delete current.expect_attribute;
            }

            // Persist current turn delay sliders into preset
            const delayMin = parseFloat(els.turnDelayMin?.value);
            const delayMax = parseFloat(els.turnDelayMax?.value);
            if (Number.isFinite(delayMin) && Number.isFinite(delayMax)) {
                current.turn_delay_min_sec = delayMin;
                current.turn_delay_max_sec = delayMax;
                current.turn_delay_disabled = els.temptFateBtn?.classList.contains('is-active') || false;
            }

            try {
                await apiJson('/api/presets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ preset: current })
                });
            } catch (e) {}
        }

        function populatePresetUI() {
            if (!state.selectedPreset || !state.presets) return;
            const current = getCurrentPreset();
            if (!current) return;

            els.presetSkillThreshold.value = current.learn_skill_threshold || 888;
            if (els.presetRunningStyle) els.presetRunningStyle.value = current.running_style || 1;
            if (els.presetDelayMin) els.presetDelayMin.value = current.run_delay_min_min ?? 0;
            if (els.presetDelayMax) els.presetDelayMax.value = current.run_delay_max_min ?? 0;
            if (els.presetTpMode) els.presetTpMode.value = (current.tp_mode === 'wait') ? 'wait' : 'carat';
            const scenarioId = Number(current.scenario_id || current.scenario || 4);
            state.scenarioType = scenarioTypes[scenarioId] || "Mant";
            if (els.presetScenario) els.presetScenario.value = String(scenarioId);
            const unityConfig = current.unity_config || {};
            if (els.unityTrainingWeight) els.unityTrainingWeight.value = unityConfig.unity_training_weight ?? 0.6;
            if (els.unityBurstWeight) els.unityBurstWeight.value = unityConfig.spirit_burst_weight ?? 5.0;
            if (els.presetUseMcts) els.presetUseMcts.checked = !!current.use_mcts;
            if (els.presetPalRecreation) els.presetPalRecreation.checked = !!current.pal_recreation_required;
            if (els.presetParentRun) els.presetParentRun.checked = !!current.parent_run;

    // Expect attribute
    const attr = current.expect_attribute || [];
    if (els.presetExpectSpeed) els.presetExpectSpeed.value = attr[0] ?? '';
    if (els.presetExpectStamina) els.presetExpectStamina.value = attr[1] ?? '';
    if (els.presetExpectPower) els.presetExpectPower.value = attr[2] ?? '';
    if (els.presetExpectGuts) els.presetExpectGuts.value = attr[3] ?? '';
    if (els.presetExpectWit) els.presetExpectWit.value = attr[4] ?? '';

            // Apply preset turn delay to the global delay module
            if (current.turn_delay_min_sec != null && current.turn_delay_max_sec != null) {
                saveDelaySettings(normalizeDelayBounds(
                    current.turn_delay_min_sec,
                    current.turn_delay_max_sec,
                    current.turn_delay_disabled || false,
                    current.turn_delay_min_sec,
                    current.turn_delay_max_sec,
                ));
            }
        }

        function bindPresetHandlers() {
            if (els.presetSelect) {
                els.presetSelect.addEventListener('change', async (e) => {
                    state.selectedPreset = e.target.value;
                    localStorage.setItem('uma_selected_preset', state.selectedPreset);
                    syncSelectedPresetRaces();
                    populatePresetUI();
                    populateTrackblazerSelect();
                    renderTrackblazer();
                    renderRaces();
                    applyPresetTeamSelection();
                });
            }

            const saveHandler = () => savePresetConfig();
            els.presetSkillThreshold?.addEventListener('change', saveHandler);
            els.presetRunningStyle?.addEventListener('change', saveHandler);
            els.presetDelayMin?.addEventListener('change', saveHandler);
            els.presetDelayMax?.addEventListener('change', saveHandler);
            els.presetTpMode?.addEventListener('change', saveHandler);
            els.presetScenario?.addEventListener('change', saveHandler);
            els.unityTrainingWeight?.addEventListener('change', saveHandler);
            els.unityBurstWeight?.addEventListener('change', saveHandler);
            els.presetUseMcts?.addEventListener('change', saveHandler);
            els.presetPalRecreation?.addEventListener('change', saveHandler);
            els.presetParentRun?.addEventListener('change', saveHandler);
            els.presetExpectSpeed?.addEventListener('change', saveHandler);
            els.presetExpectStamina?.addEventListener('change', saveHandler);
            els.presetExpectPower?.addEventListener('change', saveHandler);
            els.presetExpectGuts?.addEventListener('change', saveHandler);
            els.presetExpectWit?.addEventListener('change', saveHandler);

            els.presetEditSkillsBtn?.addEventListener('click', () => {
                if (!state.selectedPreset) return;
                activeEditTier = 0;

                els.skillModal.style.display = 'flex';
                if (els.skillSearch) els.skillSearch.value = '';
                activeSkillFilter = null;

                loadSkillData().then(() => {
                    renderSkillFilters();
                    renderSkillList();
                });
                renderSkillEditorRightSide();
            });
            els.skillModalClose?.addEventListener('click', () => { els.skillModal.style.display = 'none'; });

            els.skillSearch?.addEventListener('input', renderSkillList);

            els.skillAddTierBtn?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                if (!current.learn_skill_list) current.learn_skill_list = [];
                current.learn_skill_list.push([]);
                activeEditTier = current.learn_skill_list.length - 1;
                await savePresetConfig();
                renderSkillEditorRightSide();
            });

            document.getElementById('skill-select-all-btn')?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                const visibleNodes = els.skillList?.querySelectorAll('.skill-list-item') || [];
                let changed = false;

                visibleNodes.forEach(node => {
                    const name = node.getAttribute('data-name');
                    if (activeEditTier === null) {
                        if (!current.learn_skill_blacklist) current.learn_skill_blacklist = [];
                        if (!current.learn_skill_blacklist.includes(name)) {
                            current.learn_skill_blacklist.push(name);
                            changed = true;
                        }
                    } else {
                        if (!current.learn_skill_list) current.learn_skill_list = [];
                        if (!current.learn_skill_list[activeEditTier]) current.learn_skill_list[activeEditTier] = [];
                        if (!current.learn_skill_list[activeEditTier].includes(name)) {
                            current.learn_skill_list[activeEditTier].push(name);
                            changed = true;
                        }
                    }
                });
                if (changed) {
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                }
            });

            document.getElementById('skill-deselect-all-btn')?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                const visibleNodes = els.skillList?.querySelectorAll('.skill-list-item') || [];
                let changed = false;

                const namesToRemove = Array.from(visibleNodes).map(node => node.getAttribute('data-name'));

                if (activeEditTier === null) {
                    if (current.learn_skill_blacklist) {
                        const originalLen = current.learn_skill_blacklist.length;
                        current.learn_skill_blacklist = current.learn_skill_blacklist.filter(s => !namesToRemove.includes(s));
                        if (current.learn_skill_blacklist.length !== originalLen) changed = true;
                    }
                } else {
                    if (current.learn_skill_list && current.learn_skill_list[activeEditTier]) {
                        const originalLen = current.learn_skill_list[activeEditTier].length;
                        current.learn_skill_list[activeEditTier] = current.learn_skill_list[activeEditTier].filter(s => !namesToRemove.includes(s));
                        if (current.learn_skill_list[activeEditTier].length !== originalLen) changed = true;
                    }
                }

                if (changed) {
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                }
            });

            document.getElementById('skill-blacklist-all-btn')?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                const visibleNodes = els.skillList?.querySelectorAll('.skill-list-item') || [];
                let changed = false;

                if (!current.learn_skill_blacklist) current.learn_skill_blacklist = [];
                visibleNodes.forEach(node => {
                    const name = node.getAttribute('data-name');
                    if (!current.learn_skill_blacklist.includes(name)) {
                        current.learn_skill_blacklist.push(name);
                        changed = true;
                    }
                });

                if (changed) {
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                }
            });
            document.getElementById('skill-clear-blacklist-btn')?.addEventListener('click', async () => {
                const current = getCurrentPreset();
                if (!current) return;
                if (current.learn_skill_blacklist && current.learn_skill_blacklist.length > 0) {
                    current.learn_skill_blacklist = [];
                    await savePresetConfig();
                    renderSkillEditorRightSide();
                }
            });

            els.presetAddBtn?.addEventListener('click', async () => {
                const newName = prompt("Enter new preset name:");
                if (!newName || !newName.trim()) return;
                const normalizedName = normalizePresetName(newName);
                if (!normalizedName) {
                    alert("Preset name cannot be empty.");
                    return;
                }
                if (presetNameExists(normalizedName)) {
                    alert("A preset with that name already exists.");
                    return;
                }

                const newPreset = {
                    name: normalizedName,
                    running_style: 1,
                    learn_skill_list: [],
                    learn_skill_blacklist: [],
                    extra_race_list: [],
                    learn_skill_threshold: 888,
                    run_delay_min_min: 10,
                    run_delay_max_min: 50,
                    tp_mode: 'carat'
                };

                try {
                    const res = await apiJson('/api/presets', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ preset: newPreset })
                    });
                    if (!res.success || !res.preset?.name) {
                        alert(res.detail || "Failed to save new preset.");
                        return;
                    }
                    state.selectedPreset = res.preset.name;
                    localStorage.setItem('uma_selected_preset', state.selectedPreset);
                    await loadPresets();
                    if (els.presetSelect) els.presetSelect.value = state.selectedPreset;
                    syncSelectedPresetRaces();
                    populatePresetUI();
                    renderTrackblazer();
                    renderRaces();
                } catch (e) { alert("Failed to save new preset."); }
            });

            els.presetDelBtn?.addEventListener('click', async () => {
                if (!state.selectedPreset) return;
                const deletedName = state.selectedPreset;
                if (!confirm(`Are you sure you want to delete preset '${deletedName}'?`)) return;

                try {
                    const res = await apiJson('/api/presets/delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: deletedName })
                    });
                    if (!res.success) {
                        alert(res.detail || "Failed to delete preset.");
                        return;
                    }
                    await loadPresets();
                } catch (e) { alert("Failed to delete preset."); }
            });
        }

        async function loadPresets() {
            try {
                const res = await apiJson('/api/presets');
                if (res.success && res.presets && res.presets.length > 0) {
                    state.presets = res.presets;
                    if (els.presetSelect) {
                        els.presetSelect.innerHTML = state.presets.map(p => `<option value="${escapeAttr(p.name)}">${escapeHtml(p.name)}</option>`).join('');
                    }
                    const saved = localStorage.getItem('uma_selected_preset');
                    if (saved && state.presets.some(p => p.name === saved)) {
                        state.selectedPreset = saved;
                    } else {
                        state.selectedPreset = state.presets[0].name;
                    }
                    localStorage.setItem('uma_selected_preset', state.selectedPreset);
                    if (els.presetSelect) els.presetSelect.value = state.selectedPreset;
                    populatePresetUI();
                    populateTrackblazerSelect();
                } else {
                    state.presets = [];
                    state.selectedPreset = "";
                    localStorage.removeItem('uma_selected_preset');
                    if (els.presetSelect) els.presetSelect.innerHTML = "";
                    populatePresetUI();
                    populateTrackblazerSelect();
                }
            } catch(e) {
                state.presets = [];
                state.selectedPreset = "";
                localStorage.removeItem('uma_selected_preset');
                populatePresetUI();
                populateTrackblazerSelect();
            }
            syncStartButton();
            await loadRaceData();
        }

        function renderFriends() {
            const friends = (dashData && dashData.friends) || [];
            clearInvalidFriendSelection();
            const visibleFriends = getVisibleFriends();
            if (dashData) dashData.visibleFriends = visibleFriends;

            if (state.pendingFriendSelection) {
                const f = visibleFriends.find(v =>
                    String(v.viewer_id) === state.pendingFriendSelection.viewer_id &&
                    String(v.support_card_id) === state.pendingFriendSelection.support_card_id
                );
                if (f) {
                    selection.friend = f;
                    state.pendingFriendSelection = null;
                }
            }

            els.friendCount.innerText = `(${visibleFriends.length}/${friends.length})`;
            const filterBar = document.getElementById('friend-filter-bar');
            if (filterBar) filterBar.style.display = friends.length > 0 ? '' : 'none';
            els.friendGrid.innerHTML = visibleFriends.map(friend => {
                const imgId = friend.support_card_id || '10001';
                const lb = friend.limit_break_count ?? '?';
                return `<div class="grid-card friend-card">
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="grid-card-overlay">
                        <span class="grid-card-name">${friend.support_name || 'Unknown'}</span>
                        <span class="grid-card-kicker">${friend.type || '?'} | LB${lb}</span>
                    </div>
                </div>`;
            }).filter(Boolean).join('');
            attachFriendHandlers();
            syncFriendSelection();
            renderTeamPanel();
        }
        function appendSeenFriendIds(ids) {
            if (!dashData) return;
            const seen = new Set(dashData.friendExcludeIds || []);
            (ids || []).forEach(id => {
                if (id) seen.add(id);
            });
            dashData.friendExcludeIds = Array.from(seen);
        }

        function bindFilterHandlers() {
            const friendType = document.getElementById('friend-type-filter');
            if (friendType) {
                friendType.addEventListener('change', () => {
                    state.friendTypeFilter = friendType.value;
                    renderFriends();
                    document.getElementById('friend-filter-bar').style.display = '';
                });
            }

            const parentName = document.getElementById('parent-name-filter');
            if (parentName) parentName.addEventListener('input', () => {
                state.parentNameFilter = parentName.value || '';
                renderParents((dashData && dashData.parents) || []);
            });
            renderParentSparkFilters();
        }

        const PARENT_BLUE_SPARKS = [
            { key: 'speed', label: 'Speed', category: 'stat' },
            { key: 'stamina', label: 'Stamina', category: 'stat' },
            { key: 'power', label: 'Power', category: 'stat' },
            { key: 'guts', label: 'Guts', category: 'stat' },
            { key: 'wit', label: 'Wit', category: 'stat' },
        ];
        const PARENT_PINK_SPARKS = [
            { key: 'turf', label: 'Turf', category: 'aptitude' },
            { key: 'dirt', label: 'Dirt', category: 'aptitude' },
            { key: 'short', label: 'Short', category: 'aptitude' },
            { key: 'mile', label: 'Mile', category: 'aptitude' },
            { key: 'medium', label: 'Medium', category: 'aptitude' },
            { key: 'long', label: 'Long', category: 'aptitude' },
            { key: 'front', label: 'Front Runner', category: 'aptitude' },
            { key: 'pace', label: 'Pace Chaser', category: 'aptitude' },
            { key: 'late', label: 'Late Surger', category: 'aptitude' },
            { key: 'end', label: 'End Closer', category: 'aptitude' },
        ];
        const PARENT_SPARK_BY_KEY = {};
        [...PARENT_BLUE_SPARKS, ...PARENT_PINK_SPARKS].forEach(s => { PARENT_SPARK_BY_KEY[s.key] = s; });

        function renderParentSparkFilters() {
            const container = document.getElementById('parent-spark-filters');
            if (!container) return;
            const filters = state.parentSparkFilters || {};
            const chipHtml = spark => {
                const th = filters[spark.key] || 0;
                const tint = spark.category === 'stat' ? '96,165,250' : '244,114,182';
                const active = th > 0;
                const bg = active ? `rgba(${tint},0.22)` : 'rgba(255,255,255,0.05)';
                const border = active ? `rgb(${tint})` : 'transparent';
                const color = active ? 'var(--text-main)' : '#a1a1aa';
                const star = th === 3 ? '3★' : th > 0 ? `${th}★+` : '';
                return `<div class="parent-spark-chip" data-key="${spark.key}" style="padding:0.35rem 0.7rem; border-radius:1rem; font-size:0.75rem; cursor:pointer; background:${bg}; border:1px solid ${border}; color:${color}; font-weight:bold; transition:all 0.1s;">${spark.label}${star ? ` <span style="opacity:0.85">${star}</span>` : ''}</div>`;
            };
            const anyActive = Object.keys(filters).length > 0;
            let html = '<div style="display:flex; flex-wrap:wrap; gap:4px; margin-bottom:4px;">';
            html += PARENT_BLUE_SPARKS.map(chipHtml).join('');
            html += '</div><div style="display:flex; flex-wrap:wrap; gap:4px; align-items:center;">';
            html += PARENT_PINK_SPARKS.map(chipHtml).join('');
            if (anyActive) html += `<div id="parent-spark-clear" style="padding:0.35rem 0.7rem; border-radius:1rem; font-size:0.75rem; cursor:pointer; background:rgba(255,255,255,0.05); border:1px solid transparent; color:#a1a1aa; font-weight:bold;">Clear ✕</div>`;
            html += '</div>';
            container.innerHTML = html;

            container.querySelectorAll('.parent-spark-chip').forEach(el => {
                el.addEventListener('click', () => {
                    const key = el.getAttribute('data-key');
                    const next = ((state.parentSparkFilters[key] || 0) + 1) % 4; // off->1->2->3->off
                    if (next === 0) delete state.parentSparkFilters[key];
                    else state.parentSparkFilters[key] = next;
                    renderParentSparkFilters();
                    renderParents((dashData && dashData.parents) || []);
                });
            });
            const clear = document.getElementById('parent-spark-clear');
            if (clear) clear.addEventListener('click', () => {
                state.parentSparkFilters = {};
                renderParentSparkFilters();
                renderParents((dashData && dashData.parents) || []);
            });
        }
        async function loadFriends(refresh = false) {
            if (!dashData || state.isFetchingFriends) return;
            const isCareerActive = dashData.account && dashData.account.career && dashData.account.career.active;
            if (isCareerActive) {
                els.friendRefreshBtn.disabled = true;
                els.friendStatus.classList.remove('error');
                els.friendStatus.innerText = 'Active career, endpoint blocked';
                return;
            }
            state.isFetchingFriends = true;
            els.friendRefreshBtn.disabled = true;
            els.friendStatus.classList.remove('error');
            els.friendStatus.innerText = refresh ? 'Refreshing friends...' : 'Loading friends...';
            const excludeIds = refresh ? (dashData.friendExcludeIds || []) : [];
            try {
                const data = await apiJson('/api/career/friends', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ exclude_viewer_ids: excludeIds })
                });
                if (!data.success) throw new Error(data.detail || 'Friend load failed');
                dashData.friends = data.friends || [];
                if (data.veterans) dashData.friendVeterans = data.veterans;
                if (data.veterans_source) dashData.friendVeteransSource = data.veterans_source;
                appendSeenFriendIds(data.exclude_viewer_ids || []);
                renderFriends();
                if (data.source === 'Active Career (Skip)') {
                    els.friendStatus.innerText = 'Active career, endpoint blocked';
                    return;
                }
                const source = data.source === 'initial' ? 'initial' : 'refresh';
                const visibleCount = ((dashData && dashData.visibleFriends) || []).length;
                els.friendStatus.innerText = `${source} list: ${visibleCount}/${dashData.friends.length} cards`;
            } catch (e) {
                els.friendStatus.innerText = e.message || 'Friend load failed';
                els.friendStatus.classList.add('error');
            } finally {
                state.isFetchingFriends = false;
                const stillActive = dashData.account && dashData.account.career && dashData.account.career.active;
                els.friendRefreshBtn.disabled = !!stillActive;
            }
        }
        function attachFriendHandlers() {
            const visibleFriends = (dashData && dashData.visibleFriends) || [];
            document.querySelectorAll('#friend-grid .grid-card').forEach((el, i) => {
                el.classList.add('selectable');
                el.addEventListener('click', () => {
                    const friend = visibleFriends[i];
                    const already = selection.friend && friendKey(selection.friend) === friendKey(friend);
                    document.querySelectorAll('#friend-grid .grid-card').forEach(c => c.classList.remove('selected'));
                    selection.friend = already ? null : friend;
                    if (!already) el.classList.add('selected');
                    renderTeamPanel();
                });
            });
        }
        async function startCareer() {
            const reason = getStartMissingReason();
            if (reason || state.isStartingCareer) {
                syncStartButton();
                return;
            }
            state.isStartingCareer = true;
            syncStartButton();
            let finalMessage = '';
            let finalIsError = false;
            const activeCareer = state.account && state.account.career && state.account.career.active;
            const body = activeCareer ? {
                preset_name: state.selectedPreset,
                max_steps: 2500,
                burn_clocks: state.burnClocks,
                dev_mode: state.devEnabled,
                run_delay_min_min: Number(getCurrentPreset()?.run_delay_min_min ?? 0),
                run_delay_max_min: Number(getCurrentPreset()?.run_delay_max_min ?? 0),
                tp_mode: (getCurrentPreset()?.tp_mode === 'wait') ? 'wait' : 'carat'
            } : {
                card_id: Number(selection.trainee.id),
                support_card_ids: selection.deck.cards.map(card => Number(card.id)),
                friend_viewer_id: Number(selection.friend.viewer_id),
                friend_card_id: Number(selection.friend.support_card_id),
                // Own veterans (no viewer_id) → parent_id_1/2
                // Rental veterans (from friends, have viewer_id) → rental_viewer_id + rental_trained_chara_id
                parent_id_1: Number((selection.veterans.filter(v => !v.viewer_id)[0]?.instance_id) || 0),
                parent_id_2: Number((selection.veterans.filter(v => !v.viewer_id)[1]?.instance_id) || 0),
                rental_viewer_id: Number((selection.veterans.filter(v => v.viewer_id)[0]?.viewer_id) || 0),
                rental_trained_chara_id: Number((selection.veterans.filter(v => v.viewer_id)[0]?.trained_chara_id) || 0),
                deck_id: Number(selection.deck.id),
                scenario_id: Number(getCurrentPreset()?.scenario_id ?? getCurrentPreset()?.scenario ?? 4),
                use_tp: 30,
                difficulty_id: 0,
                difficulty: 0,
                is_boost: 0,
                boost_story_event_id: 0,
                preset_name: state.selectedPreset,
                max_steps: 2500,
                burn_clocks: state.burnClocks,
                dev_mode: state.devEnabled,
                run_delay_min_min: Number(getCurrentPreset()?.run_delay_min_min ?? 0),
                run_delay_max_min: Number(getCurrentPreset()?.run_delay_max_min ?? 0),
                tp_mode: (getCurrentPreset()?.tp_mode === 'wait') ? 'wait' : 'carat'
            };
            try {
                const data = await apiJson('/api/career/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!data.success) throw new Error(data.detail || 'Start failed');
                state.displayedClocksUsed = Number(data.runner && data.runner.clocks_used || 0);
                renderAccountStrip(data.account);
                if (data.account && data.account.career && data.account.career.active) {
                    autoLoadCareerSelection();
                    renderFriends();
                }
                startRunnerPolling();
                finalMessage = 'Career runner started';
            } catch (e) {
                finalMessage = e.message || 'Start failed';
                finalIsError = true;
                if (state.devEnabled) {
                    setDevEnabled(false, { persist: true });
                }
            } finally {
                state.isStartingCareer = false;
                syncStartButton();
                if (finalMessage) {
                    els.startStatus.innerText = finalMessage;
                    els.startStatus.classList.toggle('error', finalIsError);
                }
            }
        }

        function inheritanceGoal() {
            return {
                distance: els.inheritanceDistance ? els.inheritanceDistance.value : '',
                surface: els.inheritanceSurface ? els.inheritanceSurface.value : ''
            };
        }
        function sourceBadge(source) { return source === 'veteran' ? 'Veteran' : 'Owned'; }
        function renderInheritanceSetup(setup) {
            const raceHtml = (setup.races || []).slice(0, 5).map(r => `<span class="inherit-race-chip">${escapeHtml(r.name)} ×${r.count}</span>`).join('') || '<span class="muted">No shared races</span>';
            const sparkHtml = (setup.spark_hits || []).slice(0, 8).map(s => `<span class="inherit-spark-chip">${escapeHtml(s.name)} ${escapeHtml(s.stars)}★</span>`).join('') || '<span class="muted">No goal sparks</span>';
            return `<div class="inheritance-card">
                <div class="inheritance-card-head">
                    <strong>#${setup.rank} ${escapeHtml(setup.parent1.name)} + ${escapeHtml(setup.parent2.name)}</strong>
                    <span class="inheritance-score">${Math.round(setup.score)}</span>
                </div>
                <div class="inheritance-meta">
                    <span>${escapeHtml(sourceBadge(setup.parent1.source))}</span>
                    <span>${escapeHtml(sourceBadge(setup.parent2.source))}</span>
                    <span>Compat ${escapeHtml(setup.compat_tier)} ${escapeHtml(setup.compat_total)}</span>
                    <span>Race +${escapeHtml(setup.race_score)}</span>
                </div>
                <div class="inheritance-line"><b>Sparks</b> ${sparkHtml}</div>
                <div class="inheritance-line"><b>Run</b> ${raceHtml}</div>
            </div>`;
        }
        async function recommendInheritance() {
            if (!selection.trainee) {
                if (els.inheritanceStatus) els.inheritanceStatus.innerText = 'Select trainee first.';
                return;
            }
            if (!els.inheritanceResults) return;
            els.inheritanceRecommendBtn.disabled = true;
            els.inheritanceStatus.classList.remove('error');
            els.inheritanceStatus.innerText = 'Calculating...';
            els.inheritanceResults.innerHTML = '';
            try {
                const data = await apiJson('/api/inheritance/recommend', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        target_card_id: Number(selection.trainee.id),
                        pool: els.inheritancePool ? els.inheritancePool.value : 'both',
                        goal: inheritanceGoal(),
                        limit: 10
                    })
                });
                if (!data.success) throw new Error(data.detail || 'Recommend failed');
                els.inheritanceStatus.innerText = `${data.results.length} setups · ${data.parent_count} parents scanned`;
                els.inheritanceResults.innerHTML = data.results.map(renderInheritanceSetup).join('') || '<div class="friend-status">No setup found.</div>';
            } catch (e) {
                els.inheritanceStatus.innerText = e.message || 'Recommend failed';
                els.inheritanceStatus.classList.add('error');
            } finally {
                els.inheritanceRecommendBtn.disabled = false;
            }
        }

        function applyRunnerSettings(runner) {
            if (runner.running && runner.burn_clocks !== undefined && state.burnClocks !== runner.burn_clocks) {
                setBurnClocks(runner.burn_clocks, { persist: true });
            }
        }
        function applyRunnerClockUsage(runner) {
            const clocksUsed = Number(runner.clocks_used || 0);
            if (state.account && clocksUsed > state.displayedClocksUsed) {
                const delta = clocksUsed - state.displayedClocksUsed;
                state.account = {
                    ...state.account,
                    clocks: Math.max(0, Number(state.account.clocks || 0) - delta)
                };
                state.displayedClocksUsed = clocksUsed;
                renderAccountStrip(state.account);
            } else if (clocksUsed < state.displayedClocksUsed) {
                state.displayedClocksUsed = clocksUsed;
            }
        }
        function applyRunnerSnapshot(runner) {
            state.runner = runner;
            applyRunnerSettings(runner);
            applyRunnerClockUsage(runner);
        }
        async function refreshRunnerStatus() {
            try {
                const data = await apiJson('/api/career/runner');
                if (!data.success || !data.runner) return;
                const runner = data.runner;
                applyRunnerSnapshot(runner);

                // Sync career active flag when runner finishes
                if (runner.finished && state.account && state.account.career && state.account.career.active) {
                    state.account.career.active = false;
                    renderAccountStrip(state.account);
                }

                const rows = (runner.action_history && runner.action_history.length) ? runner.action_history : deriveActionHistory(runner.log || []);
                if (rows.length) renderActionHistory(rows);
                if (runner.running) {
                    els.startStatus.classList.toggle('error', false);
                    if (!rows.length) els.startStatus.innerText = `Turn ${runner.turn || '?'} / ${runner.last_action || 'running'} / ${runner.steps || 0}`;
                    return;
                }
                if (state.runnerTimer && !state.devEnabled) {
                    bgClearTimer(state.runnerTimer);
                    state.runnerTimer = 0;
                }
                loadRunHistory();
                if (runner.last_error) {
                    els.startStatus.classList.toggle('error', true);
                    if (!rows.length) els.startStatus.innerText = runner.last_error;
                    if (state.devEnabled) {
                        state.consecutiveRunnerFails++;
                        if (state.consecutiveRunnerFails >= 3) {
                            if (!rows.length) els.startStatus.innerText = runner.last_error + " (Auto-retry disabled due to loop)";
                            setDevEnabled(false, { persist: true });
                        }
                    }
                } else if (state.devEnabled && runner.finished && !runner.last_error) {
                    state.consecutiveRunnerFails = 0;
                    els.startStatus.classList.toggle('error', false);
                    if (!rows.length) els.startStatus.innerText = `Career finished! Restarting...`;
                    if (state.account && state.account.career) state.account.career.active = false;
                    renderAccountStrip(state.account);
                } else if (runner.steps) {
                    els.startStatus.classList.toggle('error', false);
                    if (!rows.length) els.startStatus.innerText = `Runner stopped after ${runner.steps} steps`;
                    if (state.devEnabled) {
                        state.consecutiveRunnerFails++;
                        if (state.consecutiveRunnerFails >= 3) {
                            if (!rows.length) els.startStatus.innerText = `Runner stopped after ${runner.steps} steps (Auto-retry disabled due to loop)`;
                            setDevEnabled(false, { persist: true });
                        }
                    }
                }
            } catch (e) {}
        }
        function renderActionHistory(rows) {
            if (!els.startStatus) return;
            if (!rows.length) {
                els.startStatus.innerText = '';
                return;
            }
            const formatStatsDetail = row => {
                const stats = row.stats || {};
                if (!Object.keys(stats).length) return row.detail || '';
                return [
                    `HP ${stats.hp ?? 0}/${stats.max_hp ?? 100}`,
                    `MOOD ${stats.motivation ?? 0}`,
                    `SPD ${stats.speed ?? 0} STA ${stats.stamina ?? 0} PWR ${stats.power ?? 0} GUT ${stats.guts ?? 0} WIT ${stats.wit ?? 0} SP ${stats.skill_point ?? 0}`
                ].join(' | ');
            };
            const body = rows.map(row => `
                    <tr>
                        <td>${escapeHtml(row.turn)}</td>
                        <td><span class="action-pill action-pill-${escapeAttr(normalizeHistoryAction(row).action)}">${escapeHtml(normalizeHistoryAction(row).action)}</span></td>
                        <td>${escapeHtml(row.facility)}</td>
                        <td class="action-history-detail">${escapeHtml(formatStatsDetail(row))}</td>
                    </tr>
                `).join('');
            els.startStatus.innerHTML = `
                <div class="action-history-wrap">
                    <table class="action-history-table">
                        <thead>
                            <tr>
                                <th>TURN</th>
                                <th>ACTION</th>
                                <th>FACILITY</th>
                                <th>DETAIL</th>
                            </tr>
                        </thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            `;
            const wrap = els.startStatus.querySelector('.action-history-wrap');
            if (wrap) wrap.scrollTop = wrap.scrollHeight;
        }
        function deriveActionHistory(log) {
            return log.filter(item => ['command', 'race', 'race_progress', 'finish', 'api_delay', 'turn_delay', 'complex_delay'].includes(item.action)).map(item => {
                const detail = String(item.detail || '');
                let action = item.action;
                let facility = '';
                if (action === 'command') {
                    if (detail.startsWith('training ')) {
                        action = 'train';
                        facility = detail.replace('training ', '');
                    } else if (detail.startsWith('rest ')) {
                        action = 'rest';
                        facility = detail.replace('rest ', '');
                        if (['301', '302', '303', '304', '305', '390'].includes(facility)) action = 'recreation';
                    } else if (detail.startsWith('challenge ')) {
                        action = 'rest';
                        facility = detail.replace('challenge ', '');
                    } else if (detail.startsWith('recreation ')) {
                        action = 'recreation';
                        facility = detail.replace('recreation ', '');
                    } else if (detail.startsWith('command 8:')) {
                        action = 'medic';
                    }
                } else if (action === 'race_progress') {
                    action = 'race';
                }
                return { turn: item.turn, action, facility, detail };
            });
        }
        function normalizeHistoryAction(row) {
            const facility = String(row.facility ?? '');
            if (row.action === 'rest' && ['301', '302', '303', '304', '305', '390'].includes(facility)) {
                return { ...row, action: 'recreation' };
            }
            return row;
        }
        const timerWorkerBlob = new Blob([`
            let activeTimers = {};
            self.onmessage = function(e) {
                const { action, id, ms } = e.data;
                if (action === 'setInterval') {
                    activeTimers[id] = setInterval(() => postMessage({ id }), ms);
                } else if (action === 'setTimeout') {
                    activeTimers[id] = setTimeout(() => {
                        postMessage({ id });
                        delete activeTimers[id];
                    }, ms);
                } else if (action === 'clear') {
                    clearInterval(activeTimers[id]);
                    clearTimeout(activeTimers[id]);
                    delete activeTimers[id];
                }
            };
        `], {type: 'application/javascript'});
        const timerWorker = new Worker(URL.createObjectURL(timerWorkerBlob));
        let nextTimerId = 1;
        const timerCallbacks = {};
        timerWorker.onmessage = function(e) {
            if (timerCallbacks[e.data.id]) timerCallbacks[e.data.id]();
        };
        function bgSetInterval(cb, ms) {
            const id = nextTimerId++;
            timerCallbacks[id] = cb;
            timerWorker.postMessage({ action: 'setInterval', id, ms });
            return id;
        }
        function bgSetTimeout(cb, ms) {
            const id = nextTimerId++;
            timerCallbacks[id] = () => { delete timerCallbacks[id]; cb(); };
            timerWorker.postMessage({ action: 'setTimeout', id, ms });
            return id;
        }
        function bgClearTimer(id) {
            delete timerCallbacks[id];
            timerWorker.postMessage({ action: 'clear', id });
        }
        function startRunnerPolling() {
            if (state.runnerTimer) bgClearTimer(state.runnerTimer);
            refreshRunnerStatus();
            state.runnerTimer = bgSetInterval(refreshRunnerStatus, 1500);
        }
        els.friendRefreshBtn.addEventListener('click', event => {
            event.stopPropagation();
            loadFriends(true);
        });
        els.startCareerBtn.addEventListener('click', startCareer);

        function selectDeck(index, element) {
            const alreadySelected = element.classList.contains('selected');
            document.querySelectorAll('.deck-container.selected').forEach(card => card.classList.remove('selected'));
            selection.deck = null;
            if (!alreadySelected) {
                element.classList.add('selected');
                selection.deck = dashData.validDecks[index];
            }
            renderFriends();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function selectTrainee(index, element) {
            const alreadySelected = element.classList.contains('selected');
            document.querySelectorAll('#uma-grid .grid-card.selected').forEach(card => card.classList.remove('selected'));
            selection.trainee = null;
            if (!alreadySelected) {
                element.classList.add('selected');
                selection.trainee = dashData.umas[index];
            }
            renderFriends();
            updateVetSelectability();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function selectParent(index, element) {
            if (element.classList.contains('vet-full')) return;
            if (element.classList.contains('selected')) {
                element.classList.remove('selected');
                selection.veterans = selection.veterans.filter(parent => parent._gridIdx !== index);
            } else if (selection.veterans.length < 2) {
                element.classList.add('selected');
                selection.veterans.push({ ...dashData.parents[index], _gridIdx: index });
            }
            updateVetSelectability();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function attachSelectionHandlers() {
            document.querySelectorAll('.deck-container').forEach((element, index) => {
                element.addEventListener('click', () => selectDeck(index, element));
            });
            document.querySelectorAll('#uma-grid .grid-card').forEach((element, index) => {
                element.classList.add('selectable');
                element.addEventListener('click', () => selectTrainee(index, element));
            });
        }
        function isValidDeck(deck) {
            return deck.cards.every(card => {
                const id = card.id || '';
                const name = card.name || '';
                return !id.includes('{') && !id.includes('-') && !name.includes('Unknown');
            });
        }
        function renderCounts(data) {
            els.umaCount.innerText = `(${data.umas.length})`;
            els.cardCount.innerText = `(${data.supports.length})`;
            els.parentCount.innerText = `(${data.parents.length})`;
        }
        function renderDecks(decks) {
            els.deckList.innerHTML = decks.map(deck => {
                const cards = deck.cards.map(card => {
                    const imgId = card.id || '10001';
                    const lb = card.limit_break_count ?? 0;
                    return `<div class="grid-card deck-card">
                        <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                        <div class="grid-card-overlay">
                            <span class="grid-card-kicker">${card.type || '?'} | ${card.rarity || '?'}</span>
                            <span class="grid-card-lb">${'★'.repeat(lb)}${'☆'.repeat(4 - lb)}</span>
                            <span class="grid-card-name">${card.name || 'Unknown'}</span>
                        </div>
                    </div>`;
                }).join('');
                return `<div class="deck-container">
                    <div class="deck-header">
                        <span>${deck.name.toUpperCase()}</span>
                        <span style="font-size:0.85rem; opacity:0.8">SLOT ${deck.id}</span>
                    </div>
                    <div class="deck-cards">${cards}</div>
                </div>`;
            }).join('');
        }
        function renderFactors(factors) {
            const star = String.fromCharCode(9733);
            return factors.map(factor => `
                <div class="factor-badge f-${factor.category}">
                    ${factor.name} <span class="stars">${star.repeat(factor.stars)}</span>
                </div>
            `).join('');
        }
        function renderWins(wins) {
            if (!wins || !wins.total) return '<span class="spark-win-chip">Wins --</span>';
            return `
                <span class="spark-win-chip">G1 ${wins.g1 || 0}</span>
                <span class="spark-win-chip">G2 ${wins.g2 || 0}</span>
                <span class="spark-win-chip">G3 ${wins.g3 || 0}</span>
            `;
        }
        function renderParentSparks(parent, fallbackImgId) {
            const tree = parent.tree || {};
            return ['self', 'p1', 'p2', 'gp1', 'gp2', 'gp3', 'gp4'].map(key => {
                const node = tree[key];
                if (!node || !node.factors || node.factors.length === 0) return '';
                const nodeImg = node.card_id || fallbackImgId;
                const nodeClass = key === 'self' ? 'spark-node spark-node-self'
                    : key.startsWith('gp') ? 'spark-node spark-node-gp'
                    : 'spark-node';
                return `<div class="${nodeClass}" style="--node-bg: url('/api/images/${nodeImg}.png')">
                    <div class="spark-node-header">
                        <img class="spark-node-portrait" src="/api/images/${nodeImg}.png" onerror="hideBrokenImage(this)">
                        <div class="spark-node-meta">
                            <div class="spark-node-title">${escapeHtml(node.name || `Card ${node.card_id || '?'}`)}</div>
                            <div class="spark-win-row">${renderWins(node.wins)}</div>
                        </div>
                    </div>
                    <div class="spark-factor-list">
                        ${renderFactors(node.factors)}
                    </div>
                </div>`;
            }).join('');
        }
        function renderParentStats(parent) {
            const stats = parent.stats || {};
            return [
                ['SPD', stats.speed],
                ['STA', stats.stamina],
                ['PWR', stats.power],
                ['GUT', stats.guts],
                ['WIT', stats.wit],
            ].map(([label, value]) => `<span class="vet-stat"><b>${label}</b>${Number(value || 0)}</span>`).join('');
        }
        function renderParentFactorChips(parent, limit = 5) {
            const factors = parent.factors || (((parent.tree || {}).self || {}).factors) || [];
            const star = String.fromCharCode(9733);
            return factors.slice(0, limit).map(f => `<span class="vet-mini-factor f-${escapeAttr(f.category || 'other')}">${escapeHtml(f.name || '?')} ${star.repeat(Number(f.stars || 0))}</span>`).join('');
        }
        function renderParentSkillList(parent, limit = 12) {
            const skills = parent.skills || [];
            if (!skills.length) return '<span class="vet-empty">No skills</span>';
            return skills.slice(0, limit).map(s => `<span class="vet-skill-chip">${escapeHtml(s.name || s.id || '?')}</span>`).join('');
        }
        function renderParentDetail(parent) {
            return `<div class="vet-card-detail">
                <div class="vet-stat-row">${renderParentStats(parent)}</div>
                <div class="vet-factor-row">${renderParentFactorChips(parent)}</div>
            </div>`;
        }
        function getFilteredVeteranPageParents() {
            const q = (state.veteranPageQuery || '').toLowerCase().trim();
            let parents = (dashData && dashData.parents) || [];
            let out = parents;
            if (q) {
                out = parents.filter(p => {
                    const skillText = (p.skills || []).map(s => s.name || s.id || '').join(' ').toLowerCase();
                    const factorText = (p.factors || []).map(f => f.name || '').join(' ').toLowerCase();
                    return (p.name || '').toLowerCase().includes(q)
                        || String(p.instance_id || '').includes(q)
                        || String(p.card_id || '').includes(q)
                        || skillText.includes(q)
                        || factorText.includes(q);
                });
            }
            const sort = state.veteranSort || 'date_desc';
            const numericValue = value => {
                if (value == null || value === '') return 0;
                const n = Number(value);
                if (Number.isFinite(n)) return n;
                const parsed = Date.parse(value);
                return Number.isFinite(parsed) ? parsed : 0;
            };
            const value = p => {
                if (sort.startsWith('point')) return numericValue(p.rank_score);
                if (sort.startsWith('rank')) return numericValue(p.rank);
                // API often lacks explicit acquired timestamp; trained_chara_id tracks creation order reliably.
                return numericValue(p.acquired_at) || numericValue(p.instance_id);
            };
            const dir = sort.endsWith('asc') ? 1 : -1;
            return [...out].sort((a, b) => {
                const diff = value(a) - value(b);
                if (diff) return diff * dir;
                return (numericValue(a.instance_id) - numericValue(b.instance_id)) * dir;
            });
        }
        function syncVeteranRemoveButton() {
            const count = state.veteranPageSelected.size;
            if (els.veteranRemoveBtn) {
                els.veteranRemoveBtn.disabled = count === 0 || state.isRemovingVeterans;
                els.veteranRemoveBtn.textContent = state.isRemovingVeterans ? 'REMOVING...' : `REMOVE SELECTED${count ? ' (' + count + ')' : ''}`;
            }
            if (els.veteranPageStatus) {
                els.veteranPageStatus.textContent = count ? `${count} selected` : '';
            }
        }
        function veteranPageCard(parent) {
            const id = Number(parent.instance_id || 0);
            const checked = state.veteranPageSelected.has(id) ? ' checked' : '';
            const imgId = parent.card_id || '100101';
            return `<div class="veteran-page-card${checked ? ' selected' : ''}" data-veteran-id="${id}">
                <label class="veteran-check"><input type="checkbox" data-veteran-check="${id}"${checked}> REMOVE</label>
                <img class="veteran-page-img" src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                <div class="veteran-page-main">
                    <div class="veteran-page-top">
                        <span class="veteran-page-name">${escapeHtml(parent.name || 'Unknown')}</span>
                        <span class="rank-badge veteran-rank-inline">${rankMap[parent.rank] || '??'}</span>
                        <span class="veteran-page-id">ID ${escapeHtml(parent.instance_id || '?')} · ${escapeHtml(parent.rank_score || 0)}</span>
                    </div>
                    <div class="vet-stat-row veteran-page-stats">${renderParentStats(parent)}</div>
                    <div class="vet-factor-row veteran-page-factors">${renderParentFactorChips(parent, 12)}</div>
                    <div class="vet-skill-list veteran-page-skills">${renderParentSkillList(parent, 60)}</div>
                </div>
            </div>`;
        }
        function renderVeteranDetail(parent) {
            if (!parent) return '';
            const imgId = parent.card_id || '100101';
            return `<div class="veteran-detail-head">
                <img class="veteran-detail-img" src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                <div>
                    <div class="veteran-detail-name">${escapeHtml(parent.name || 'Unknown')}</div>
                    <div class="veteran-page-id">ID ${escapeHtml(parent.instance_id || '?')} · ${escapeHtml(parent.rank_score || 0)} · ${rankMap[parent.rank] || '??'}</div>
                    <div class="vet-stat-row veteran-page-stats">${renderParentStats(parent)}</div>
                </div>
            </div>
            <div class="vet-tooltip-section">
                <div class="vet-tooltip-label">SKILLS</div>
                <div class="vet-skill-list">${renderParentSkillList(parent, 999)}</div>
            </div>
            <div class="vet-tooltip-section">
                <div class="vet-tooltip-label">SELF / PARENT / GRANDPARENT FACTORS</div>
                <div class="sparks-lineage-grid veteran-detail-lineage">${renderParentSparks(parent, imgId)}</div>
            </div>`;
        }
        function openVeteranDetail(id) {
            const parent = ((dashData && dashData.parents) || []).find(p => Number(p.instance_id || 0) === Number(id));
            if (!parent || !els.veteranDetailDrawer || !els.veteranDetailContent) return;
            els.veteranDetailContent.innerHTML = renderVeteranDetail(parent);
            els.veteranDetailDrawer.classList.add('open');
            els.veteranDetailDrawer.setAttribute('aria-hidden', 'false');
            if (els.veteranDetailBackdrop) els.veteranDetailBackdrop.style.display = 'block';
        }
        function closeVeteranDetail() {
            if (els.veteranDetailDrawer) {
                els.veteranDetailDrawer.classList.remove('open');
                els.veteranDetailDrawer.setAttribute('aria-hidden', 'true');
            }
            if (els.veteranDetailBackdrop) els.veteranDetailBackdrop.style.display = 'none';
        }
        function renderVeteranPage() {
            if (!els.veteranPageGrid) return;
            const parents = (dashData && dashData.parents) || [];
            const visible = getFilteredVeteranPageParents();
            const liveIds = new Set(parents.map(p => Number(p.instance_id || 0)));
            [...state.veteranPageSelected].forEach(id => { if (!liveIds.has(id)) state.veteranPageSelected.delete(id); });
            if (els.veteranPageCount) els.veteranPageCount.textContent = `(${visible.length}/${parents.length})`;
            els.veteranPageGrid.innerHTML = visible.length ? visible.map(veteranPageCard).join('') : '<div class="vet-count-msg">No veterans match</div>';
            document.querySelectorAll('[data-veteran-check]').forEach(input => {
                input.addEventListener('change', event => {
                    event.stopPropagation();
                    const id = Number(event.currentTarget.dataset.veteranCheck || 0);
                    if (!id) return;
                    if (event.currentTarget.checked) state.veteranPageSelected.add(id);
                    else state.veteranPageSelected.delete(id);
                    renderVeteranPage();
                });
                input.addEventListener('click', event => event.stopPropagation());
            });
            document.querySelectorAll('#veteran-page-grid .veteran-page-card').forEach(card => {
                card.addEventListener('click', event => {
                    if (event.target.closest('.veteran-check')) return;
                    openVeteranDetail(card.dataset.veteranId);
                });
            });
            syncVeteranRemoveButton();
        }
        async function removeSelectedVeterans() {
            const ids = [...state.veteranPageSelected];
            if (!ids.length || state.isRemovingVeterans) return;
            if (!window.confirm(`Remove ${ids.length} trained/veteran Umamusume?\n\nIDs: ${ids.join(', ')}\n\nThis cannot be undone.`)) return;
            state.isRemovingVeterans = true;
            syncVeteranRemoveButton();
            try {
                const data = await apiJson('/api/veteran/remove', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ trained_chara_id_array: ids })
                });
                if (!data || data.success === false) throw new Error((data && data.detail) || 'Remove failed');
                state.veteranPageSelected.clear();
                await renderDashboard(data, { keepRoute: true });
                if (window.location.pathname === '/veteran') navigateVeteranPage(false);
                if (els.veteranPageStatus) els.veteranPageStatus.textContent = `Removed ${ids.length}; data reloaded`;
            } catch (e) {
                if (els.veteranPageStatus) els.veteranPageStatus.textContent = `Error: ${e.message}`;
            } finally {
                state.isRemovingVeterans = false;
                syncVeteranRemoveButton();
            }
        }
        function renderParents(parents) {
            const nameQ = (state.parentNameFilter || '').toLowerCase().trim();
            const sparkFilters = state.parentSparkFilters || {};
            const sparkSpecs = Object.keys(sparkFilters).map(key => {
                const spark = PARENT_SPARK_BY_KEY[key];
                return { label: spark.label, category: spark.category, min: sparkFilters[key] };
            });

            let filtered = parents;
            if (nameQ) {
                filtered = filtered.filter(p => (p.name || '').toLowerCase().includes(nameQ));
            }
            if (sparkSpecs.length) {
                // OR: parent passes if any active spark chip is satisfied in self/p1/p2
                filtered = filtered.filter(p => {
                    const tree = p.tree || {};
                    for (const key of ['self', 'p1', 'p2']) {
                        const node = tree[key];
                        if (!node || !node.factors) continue;
                        for (const f of node.factors) {
                            for (const s of sparkSpecs) {
                                if (f.category === s.category && (f.name || '') === s.label && (f.stars || 0) >= s.min) return true;
                            }
                        }
                    }
                    return false;
                });
            }

            els.parentGrid.innerHTML = filtered.map((parent, fi) => {
                const imgId = parent.card_id || '100101';
                // Find the original index in the full parents array for selection
                const origIdx = parents.indexOf(parent);
                return `<div class="grid-card" data-pidx="${origIdx}">
                    <div class="rank-badge">${rankMap[parent.rank] || '??'}</div>
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="sparks-tooltip" style="--spark-bg: url('/api/images/${imgId}.png')">
                        <div class="sparks-tooltip-title"></div>
                        <div class="sparks-tooltip-scroll">
                            <div class="vet-tooltip-section">
                                <div class="vet-tooltip-label">STATS</div>
                                <div class="vet-stat-row vet-stat-row-tooltip">${renderParentStats(parent)}</div>
                            </div>
                            <div class="vet-tooltip-section">
                                <div class="vet-tooltip-label">SKILLS</div>
                                <div class="vet-skill-list">${renderParentSkillList(parent, 40)}</div>
                            </div>
                            <div class="sparks-lineage-grid">
                                ${renderParentSparks(parent, imgId)}
                            </div>
                        </div>
                    </div>
                    <div class="grid-card-overlay parent-card-overlay">
                        <span class="grid-card-kicker">ID: ${escapeHtml(parent.instance_id || '?')} · ${escapeHtml(parent.rank_score || 0)}</span>
                        <span class="grid-card-name">${escapeHtml(parent.name || 'Unknown')}</span>
                        ${renderParentDetail(parent)}
                    </div>
                </div>`;
            }).join('');
            if (els.parentCount) {
                const total = parents.length;
                const shown = filtered.length;
                els.parentCount.innerText = shown < total ? `(${shown}/${total})` : `(${total})`;
            }
            // Re-bind spark tooltips and parent click handlers (DOM was re-created)
            bindSparkTooltips();
            document.querySelectorAll('#parent-grid .grid-card').forEach((element) => {
                element.classList.remove('vet-full');
                element.classList.add('selectable');
                element.addEventListener('click', () => {
                    const pidx = parseInt(element.dataset.pidx, 10);
                    if (!isNaN(pidx)) selectParent(pidx, element);
                });
            });
            // Restore selected state for already-chosen parents (DOM was re-created)
            selection.veterans.forEach(vet => {
                const el = document.querySelector(`#parent-grid .grid-card[data-pidx="${vet._gridIdx}"]`);
                if (el) el.classList.add('selected');
            });
            updateVetSelectability();
            syncFriendSelection();
            renderTeamPanel();
        }
        function renderTrainees(umas) {
            els.umaGrid.innerHTML = umas.map(uma => {
                const imgId = uma.id || '100101';
                return `<div class="grid-card">
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="grid-card-overlay"><span class="grid-card-name">${uma.name || 'Unknown'}</span></div>
                </div>`;
            }).join('');
        }
        function renderSupports(supports) {
            els.cardGrid.innerHTML = supports.map(card => {
                const imgId = card.id || '10001';
                const lb = card.limit_break_count ?? 0;
                return `<div class="grid-card support-card">
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="grid-card-overlay">
                        <span class="grid-card-kicker">${(card.rarity || '?') + ' | ' + (card.type || '?')}</span>
                        <span class="grid-card-lb">${'★'.repeat(lb)}${'☆'.repeat(4 - lb)}</span>
                        <span class="grid-card-name">${card.name || 'Unknown'}</span>
                    </div>
                </div>`;
            }).join('');
        }
        let dailiesPoll = null;
        let dailiesVetsLoaded = false;

        function loadDailyVeterans() {
            if (!els.dailyVeteran || !dashData) return;
            const previous = els.dailyVeteran.value;
            const veterans = (dashData.parents || [])
                .filter(v => Number(v.instance_id || 0) > 0)
                .slice()
                .sort((a, b) => Number(b.rank_score || 0) - Number(a.rank_score || 0));
            els.dailyVeteran.innerHTML = veterans.length
                ? veterans.map(v => {
                    const id = Number(v.instance_id || 0);
                    const name = v.name || v.chara_name || `Veteran #${id}`;
                    const score = Number(v.rank_score || 0).toLocaleString();
                    return `<option value="${id}">${escapeHtml(name)} — ${score}</option>`;
                }).join('')
                : '<option value="0">No veterans available</option>';
            if (previous && veterans.some(v => String(v.instance_id) === previous)) {
                els.dailyVeteran.value = previous;
            }
            dailiesVetsLoaded = true;
        }

        function renderDailies(status) {
            const st = status || {};
            const running = !!st.running;
            if (els.dailiesRun) els.dailiesRun.style.display = running ? 'none' : '';
            if (els.dailiesStop) els.dailiesStop.style.display = running ? '' : 'none';
            if (els.dailiesLive) els.dailiesLive.classList.toggle('paused', !running);
            if (els.dailiesLiveText) {
                els.dailiesLiveText.textContent = running ? 'Running' : st.finished ? 'Done' : 'Idle';
            }
            if (els.dailiesTask) els.dailiesTask.textContent = st.task || '';
            if (!els.dailiesLog) return;
            const lines = Array.isArray(st.log) ? st.log : [];
            if (!lines.length) {
                els.dailiesLog.innerHTML = '<div class="console-empty">Select tasks above and press Run Dailies.</div>';
                return;
            }
            const atBottom = els.dailiesLog.scrollHeight - els.dailiesLog.scrollTop - els.dailiesLog.clientHeight < 48;
            els.dailiesLog.innerHTML = lines.map(line => {
                const date = new Date(Number(line.ts || 0) * 1000);
                const timeText = [date.getHours(), date.getMinutes(), date.getSeconds()]
                    .map(value => String(value).padStart(2, '0')).join(':');
                const level = ['info', 'warning', 'error'].includes(line.level) ? line.level : 'info';
                return `<div class="daily-log-line lvl-${level}"><span class="daily-log-time">${timeText}</span><span>${escapeHtml(line.msg || '')}</span></div>`;
            }).join('');
            if (atBottom) els.dailiesLog.scrollTop = els.dailiesLog.scrollHeight;
        }

        async function pollDailies() {
            try {
                const response = await fetch("/api/dailies/status");
                const data = await response.json();
                renderDailies(data.status || {});
                if (data.running && !dailiesPoll) {
                    dailiesPoll = setInterval(pollDailies, 2000);
                } else if (!data.running && dailiesPoll) {
                    clearInterval(dailiesPoll);
                    dailiesPoll = null;
                }
            } catch (_) {}
        }

        async function loadLegendOptions() {
            if (!els.dailyLegendId) return;
            const previous = els.dailyLegendId.value;
            els.dailyLegendId.innerHTML = '<option value="0">Loading available bosses…</option>';
            try {
                const response = await fetch("/api/dailies/legend_options", { method: 'POST' });
                const data = await response.json();
                const options = Array.isArray(data.legend_races) ? data.legend_races : [];
                if (!options.length) {
                    els.dailyLegendId.innerHTML = `<option value="0">${escapeHtml(data.detail || 'None available today')}</option>`;
                    return;
                }
                els.dailyLegendId.innerHTML = options.map(option => {
                    const suffix = option.is_played ? ' (done today)' : option.is_cleared ? ' (cleared)' : '';
                    return `<option value="${Number(option.id || 0)}">${escapeHtml(option.boss || `Boss #${option.id}`)}${escapeHtml(suffix)}</option>`;
                }).join('');
                if (previous && options.some(option => String(option.id) === previous)) {
                    els.dailyLegendId.value = previous;
                }
            } catch (_) {
                els.dailyLegendId.innerHTML = '<option value="0">Failed to load</option>';
            }
        }

        async function initDailies() {
            if (!dailiesVetsLoaded) loadDailyVeterans();
            await Promise.all([loadLegendOptions(), pollDailies()]);
        }

        async function runDailies() {
            const body = {
                team_trials: !!els.dailyTeamTrials?.checked,
                daily_races: !!els.dailyDailyRaces?.checked,
                legend_races: !!els.dailyLegendRaces?.checked,
                daily_shop: !!els.dailyShop?.checked,
                trained_chara_id: Number(els.dailyVeteran?.value || 0),
                opponent_strength: Number(els.dailyOpponent?.value || 1),
                legend_race_id: Number(els.dailyLegendId?.value || 0),
            };
            if (els.dailiesRun) els.dailiesRun.disabled = true;
            try {
                const response = await fetch("/api/dailies/run", {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await response.json();
                if (!data.success) {
                    renderDailies({
                        finished: true,
                        log: [{ ts: Date.now() / 1000, level: 'error', msg: data.detail || 'Failed to start dailies.' }],
                    });
                    return;
                }
                renderDailies(data.status || {});
                if (!dailiesPoll) dailiesPoll = setInterval(pollDailies, 2000);
            } catch (error) {
                renderDailies({
                    finished: true,
                    log: [{ ts: Date.now() / 1000, level: 'error', msg: error.message || 'Dailies request failed.' }],
                });
            } finally {
                if (els.dailiesRun) els.dailiesRun.disabled = false;
            }
        }

        async function stopDailies() {
            try {
                const response = await fetch("/api/dailies/stop", { method: 'POST' });
                const data = await response.json();
                renderDailies(data.status || {});
            } catch (_) {}
        }

        function showDashboardView(data) {
            document.body.classList.add('dashboard-mode');
            document.body.classList.remove('veteran-mode');
            document.body.classList.remove('dailies-mode');
            els.loginView.style.display = 'none';
            els.dashboardView.style.display = '';
            els.dashboardView.classList.add('active');
            if (els.veteranView) els.veteranView.style.display = 'none';
            if (els.dailiesView) els.dailiesView.style.display = 'none';
            els.logoutBtn.style.display = 'block';
            if (els.dashboardNavBtn) els.dashboardNavBtn.style.display = 'block';
            if (els.dailiesNavBtn) els.dailiesNavBtn.style.display = 'block';
            if (els.veteranNavBtn) els.veteranNavBtn.style.display = 'block';
            showNavbar();
            renderAccountStrip(data.account);
            syncDashboardHeight();
        }
        function navigateVeteranPage(push = true) {
            if (!dashData) return;
            if (push) window.history.pushState({}, '', '/veteran');
            els.loginView.style.display = 'none';
            els.dashboardView.style.display = 'none';
            els.dashboardView.classList.remove('active');
            if (els.veteranView) els.veteranView.style.display = 'block';
            if (els.dailiesView) els.dailiesView.style.display = 'none';
            document.body.classList.add('dashboard-mode');
            document.body.classList.add('veteran-mode');
            document.body.classList.remove('dailies-mode');
            showNavbar();
            renderVeteranPage();
        }
        function navigateDailiesPage(push = true) {
            if (!dashData) return;
            if (push) window.history.pushState({}, '', '/dailies');
            closeVeteranDetail();
            els.loginView.style.display = 'none';
            els.dashboardView.style.display = 'none';
            els.dashboardView.classList.remove('active');
            if (els.veteranView) els.veteranView.style.display = 'none';
            if (els.dailiesView) els.dailiesView.style.display = 'block';
            document.body.classList.add('dashboard-mode');
            document.body.classList.remove('veteran-mode');
            document.body.classList.add('dailies-mode');
            els.logoutBtn.style.display = 'block';
            if (els.dashboardNavBtn) els.dashboardNavBtn.style.display = 'block';
            if (els.dailiesNavBtn) els.dailiesNavBtn.style.display = 'block';
            if (els.veteranNavBtn) els.veteranNavBtn.style.display = 'block';
            showNavbar();
            initDailies();
        }

        function navigateDashboardPage(push = true) {
            if (!dashData) return;
            if (push) window.history.pushState({}, '', '/');
            closeVeteranDetail();
            showDashboardView(dashData);
            renderVeteranPage();
        }

        function autoLoadCareerSelection() {
            const activeCareer = state.account && state.account.career && state.account.career.active ? state.account.career : null;
            if (!activeCareer) return;

            resetSelection();
            document.querySelectorAll('.deck-container.selected, #uma-grid .grid-card.selected, #parent-grid .grid-card.selected, #friend-grid .grid-card.selected')
                .forEach(el => el.classList.remove('selected'));

            selectCareerDeck(activeCareer);

            if (activeCareer.card_id && dashData.umas) {
                const umaIdx = dashData.umas.findIndex(u => String(u.id) === String(activeCareer.card_id));
                if (umaIdx >= 0) {
                    selection.trainee = dashData.umas[umaIdx];
                    const umaEls = document.querySelectorAll('#uma-grid .grid-card');
                    if (umaEls[umaIdx]) umaEls[umaIdx].classList.add('selected');
                }
            }

            if (dashData.parents) {
                const p1 = activeCareer.parent_id_1;
                const p2 = activeCareer.parent_id_2;

                if (p1 || p2) {
                    dashData.parents.forEach((p, idx) => {
                        const pId = Number(p.instance_id);
                        if ((p1 && pId === Number(p1)) || (p2 && pId === Number(p2))) {
                            if (selection.veterans.length < 2 && !selection.veterans.find(v => Number(v.instance_id) === pId)) {
                                p._gridIdx = idx;
                                selection.veterans.push(p);
                                const parentEl = document.querySelector(`#parent-grid .grid-card[data-pidx="${idx}"]`);
                                if (parentEl) parentEl.classList.add('selected');
                            }
                        }
                    });
                    updateVetSelectability();
                }
            }

            selectCareerFriend(activeCareer);
            renderTeamPanel();
        }

        function applyServerSelection(serverSelection) {
            if (!serverSelection) return;
            if (serverSelection.deck && dashData.validDecks) {
                const deckIdx = dashData.validDecks.findIndex(d => Number(d.id) === Number(serverSelection.deck.id));
                if (deckIdx >= 0) {
                    selection.deck = dashData.validDecks[deckIdx];
                    const deckEls = document.querySelectorAll('.deck-container');
                    if (deckEls[deckIdx]) deckEls[deckIdx].classList.add('selected');
                }
            }
            if (serverSelection.trainee && dashData.umas) {
                const umaIdx = dashData.umas.findIndex(u => String(u.id) === String(serverSelection.trainee.id));
                if (umaIdx >= 0) {
                    selection.trainee = dashData.umas[umaIdx];
                    const umaEls = document.querySelectorAll('#uma-grid .grid-card');
                    if (umaEls[umaIdx]) umaEls[umaIdx].classList.add('selected');
                }
            }
            if (serverSelection.veterans && dashData.parents) {
                serverSelection.veterans.forEach(v => {
                    const pIdx = dashData.parents.findIndex(p => Number(p.instance_id) === Number(v.instance_id));
                    if (pIdx >= 0 && selection.veterans.length < 2) {
                        const parent = dashData.parents[pIdx];
                        parent._gridIdx = pIdx;
                        selection.veterans.push(parent);
                        const parentEl = document.querySelector(`#parent-grid .grid-card[data-pidx="${pIdx}"]`);
                        if (parentEl) parentEl.classList.add('selected');
                    }
                });
                updateVetSelectability();
                updateAptitudePreview();
            }
            if (serverSelection.friend) {
                state.pendingFriendSelection = {
                    viewer_id: String(serverSelection.friend.viewer_id),
                    support_card_id: String(serverSelection.friend.support_card_id)
                };
            }
        }

        function formatRunDuration(sec) {
            if (sec == null || sec < 0) return '—';
            const h = Math.floor(sec / 3600);
            const m = Math.floor((sec % 3600) / 60);
            const s = sec % 60;
            if (h > 0) return `${h}h ${m}m`;
            if (m > 0) return `${m}m ${s}s`;
            return `${s}s`;
        }

        function renderRunHistory(runs) {
            const el = document.getElementById('run-history-list');
            if (!el) return;
            if (!runs || !runs.length) {
                el.innerHTML = '<div class="run-history-empty">No completed runs yet.</div>';
                return;
            }
            const rows = runs.map(r => {
                const sc = r.status === 'finished' ? 'run-status-ok' : r.status === 'error' ? 'run-status-err' : 'run-status-warn';
                const date = r.started_at ? r.started_at.replace('T', ' ').slice(0, 16) : '—';
                const fans = r.final_fans != null ? Number(r.final_fans).toLocaleString() : '—';
                return `<tr>
                    <td class="run-history-date">${escapeHtml(date)}</td>
                    <td>${escapeHtml(formatRunDuration(r.duration_sec))}</td>
                    <td><span class="run-status ${escapeAttr(sc)}">${escapeHtml(r.status || '—')}</span></td>
                    <td>${escapeHtml(r.preset_name || '—')}</td>
                    <td>${escapeHtml(String(r.final_turn || 0))}</td>
                    <td>${escapeHtml(fans)}</td>
                </tr>`;
            }).join('');
            el.innerHTML = `<div class="run-history-wrap"><table class="run-history-table">
                <thead><tr><th>DATE</th><th>DURATION</th><th>STATUS</th><th>PRESET</th><th>TURN</th><th>FANS</th></tr></thead>
                <tbody>${rows}</tbody>
            </table></div>`;
        }

        async function loadRunHistory() {
            try {
                const data = await apiJson('/api/career/history');
                if (data && data.success) renderRunHistory(data.runs);
            } catch(e) {}
        }

        async function renderDashboard(data, options = {}) {
            dashData = data;
            dashData.validDecks = data.decks.filter(isValidDeck);
            dashData.friends = data.friends || [];
            dashData.friendExcludeIds = data.friendExcludeIds || [];
            const keptRoute = options.keepRoute ? window.location.pathname : '/';
            if (keptRoute === '/veteran') {
                els.loginView.style.display = 'none';
                els.dashboardView.style.display = 'none';
                if (els.veteranView) els.veteranView.style.display = 'block';
                if (els.dailiesView) els.dailiesView.style.display = 'none';
                document.body.classList.add('dashboard-mode');
                document.body.classList.add('veteran-mode');
                document.body.classList.remove('dailies-mode');
                els.logoutBtn.style.display = 'block';
                if (els.dashboardNavBtn) els.dashboardNavBtn.style.display = 'block';
                if (els.dailiesNavBtn) els.dailiesNavBtn.style.display = 'block';
                if (els.veteranNavBtn) els.veteranNavBtn.style.display = 'block';
                showNavbar();
            } else if (keptRoute === '/dailies') {
                els.loginView.style.display = 'none';
                els.dashboardView.style.display = 'none';
                if (els.veteranView) els.veteranView.style.display = 'none';
                if (els.dailiesView) els.dailiesView.style.display = 'block';
                document.body.classList.add('dashboard-mode');
                document.body.classList.remove('veteran-mode');
                document.body.classList.add('dailies-mode');
                els.logoutBtn.style.display = 'block';
                if (els.dashboardNavBtn) els.dashboardNavBtn.style.display = 'block';
                if (els.dailiesNavBtn) els.dailiesNavBtn.style.display = 'block';
                if (els.veteranNavBtn) els.veteranNavBtn.style.display = 'block';
                showNavbar();
            } else {
                showDashboardView(data);
            }
            renderCounts(data);
            renderDecks(dashData.validDecks);
            renderParents(data.parents);
            renderVeteranPage();
            renderTrainees(dashData.umas);
            renderSupports(data.supports);
            resetSelection();
            if (data.selection) applyServerSelection(data.selection);
            autoLoadCareerSelection();

            await loadPresets();
            applyPresetTeamSelection();
            if (!dashData.friends.length) {
                loadFriends(false);
            } else {
                renderFriends();
            }
            bindSparkTooltips();
            attachSelectionHandlers();
            bindRaceHandlers();
            bindPresetHandlers();
            bindTrackblazerSchedule();
            bindFilterHandlers();
            renderTeamPanel();

            startRunnerPolling();
            loadRunHistory();
            makeSectionToggle('run-history-toggle', 'run-history-chevron', 'run-history-body');
            await waitForDomPaint(2);
            setLoadingScreen(false);
            await waitForDomPaint(2);
            if (options.animateIntro !== false) {
                playBrandIntro();
                if (options.waitForIntro) await sleep(780);
            }

            // --- Advisor Panel ---
            renderAdvisorPanel();
            // --- Friend Manage ---
            bindFriendManage();
            // --- Friend Veterans ---
            makeSectionToggle('friend-vets-toggle', 'friend-vets-chevron', 'friend-vets-body', true);
            loadFriendVeterans(false);
            els.friendVetRefreshBtn?.addEventListener('click', () => loadFriendVeterans(true));
            els.friendVetSearch?.addEventListener('input', () => renderFriendVeterans());
            els.friendVetRank?.addEventListener('change', () => renderFriendVeterans());
            els.friendVetSparkToggle?.addEventListener('change', () => renderFriendVeterans());
            bindVetHandlers();
            }

            async function restoreSession() {
            try {
                const data = await apiJson('/api/session?t=' + Date.now());
                if (data && data.success) {
                    const keepRoute = window.location.pathname === '/veteran' || window.location.pathname === '/dailies';
                    await renderDashboard(data, { animateIntro: true, waitForIntro: false, keepRoute });
                    if (window.location.pathname === '/veteran') navigateVeteranPage(false);
                    else if (window.location.pathname === '/dailies') navigateDailiesPage(false);
                }
                else {
                    hideNavbar();
                    setLoadingScreen(false);
                }
            } catch (e) {
                hideNavbar();
                setLoadingScreen(false);
            }
        }
        els.veteranNavBtn?.addEventListener('click', navigateVeteranPage);
        els.dailiesNavBtn?.addEventListener('click', navigateDailiesPage);
        els.dashboardNavBtn?.addEventListener('click', navigateDashboardPage);
        els.dailiesRun?.addEventListener('click', runDailies);
        els.dailiesStop?.addEventListener('click', stopDailies);
        els.veteranPageSearch?.addEventListener('input', () => {
            state.veteranPageQuery = els.veteranPageSearch.value || '';
            renderVeteranPage();
        });
        els.veteranSortSelect?.addEventListener('change', () => {
            state.veteranSort = els.veteranSortSelect.value || 'date_desc';
            renderVeteranPage();
        });
        els.veteranSelectAllBtn?.addEventListener('click', () => {
            getFilteredVeteranPageParents().forEach(p => {
                const id = Number(p.instance_id || 0);
                if (id) state.veteranPageSelected.add(id);
            });
            renderVeteranPage();
        });
        els.veteranClearBtn?.addEventListener('click', () => {
            state.veteranPageSelected.clear();
            renderVeteranPage();
        });
        els.veteranRemoveBtn?.addEventListener('click', removeSelectedVeterans);
        els.veteranDetailClose?.addEventListener('click', closeVeteranDetail);
        els.veteranDetailBackdrop?.addEventListener('click', closeVeteranDetail);
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') closeVeteranDetail();
        });
        window.addEventListener('popstate', () => {
            if (window.location.pathname === '/veteran') navigateVeteranPage(false);
            else if (window.location.pathname === '/dailies') navigateDailiesPage(false);
            else navigateDashboardPage(false);
        });
        bindDelayControls();
        bindMasterDataControls();
        setLoadingScreen(true);
        restoreSession();

        // ==== ADVISOR PANEL ============================================
        function renderAdvisorPanel() {
            const panel = els.advisorPanel;
            if (!panel) return;
            if (!dashData) {
                panel.innerHTML = '<div class="advisor-header">PARENT ADVISOR <span style="font-weight:400;color:var(--text-muted);text-transform:none">— login to load</span></div>';
                return;
            }
            if (!dashData.friendVeterans || !dashData.friendVeterans.length) {
                panel.innerHTML = '<div class="advisor-header">PARENT ADVISOR <span style="font-weight:400;color:var(--text-muted);text-transform:none">— refresh friends to load veteran data</span></div>';
                return;
            }
            const sel = selection || {};
            const cardId = (sel.trainee || {}).id || (sel.trainee || {}).card_id || '';
            const presetName = el => el && el.value || '';
            const style = (sel.preset) ? '' : 'opacity:0.5;pointer-events:none';
            panel.innerHTML = `
                <div class="advisor-header">PARENT ADVISOR</div>
                <div class="advisor-row">
                    <button id="advisor-refresh-btn" class="btn btn-sm" type="button" style="${style}">REFRESH</button>
                    <span id="advisor-status" class="advisor-status"></span>
                </div>
                <div id="advisor-results" class="advisor-results"></div>
            `;
            const refreshBtn = document.getElementById('advisor-refresh-btn');
            if (refreshBtn) refreshBtn.addEventListener('click', () => updateAdvisorRecommendations());
        }

        async function updateAdvisorRecommendations() {
            const status = document.getElementById('advisor-status');
            const results = document.getElementById('advisor-results');
            if (!results) return;
            const sel = selection || {};
            const traineeCardId = (sel.trainee || {}).id || (sel.trainee || {}).card_id || 0;
            const presetName = (sel.preset || '');
            let runningStyle = 0;
            try {
                const presetData = await apiJson('/api/presets?t=' + Date.now());
                if (presetData && presetData.success) {
                    const p = (presetData.presets || []).find(x => x.name === presetName);
                    if (p) runningStyle = p.running_style || 0;
                }
            } catch (e) {}
            if (!traineeCardId) {
                if (status) status.textContent = 'Select a trainee first';
                return;
            }
            if (status) status.textContent = 'Loading...';
            try {
                const data = await apiJson('/api/advisor/recommendations', {
                    method: 'POST',
                    body: JSON.stringify({ trainee_card_id: Number(traineeCardId), running_style: Number(runningStyle) }),
                    headers: { 'Content-Type': 'application/json' }
                });
                if (data && data.success) {
                    const recs = (data.recommendations || []).slice(0, 24);
                    if (status) status.textContent = `${recs.length} recommendations`;
                    results.innerHTML = recs.map(r => `
                        <div class="advisor-card">
                            <img src="/api/images/${r.card_id || '10001'}.png" onerror="hideBrokenImage(this)" style="width:2.2rem;height:2.2rem;object-fit:cover;border-radius:0.3rem;">
                            <div>
                                <div style="font-weight:800;color:var(--text-main)">${r.chara_name || r.name || 'Unknown'}</div>
                                <div style="font-size:0.65rem;color:var(--text-muted)">${r.trainer_name || r.source || ''} · ${r.viewer_id || r.instance_id || ''}</div>
                            </div>
                            <div class="advisor-card-score">${Math.round((r.advisor || {}).score || 0)}</div>
                        </div>
                    `).join('');
                } else {
                    if (status) status.textContent = data?.detail || 'Failed';
                }
            } catch (e) {
                if (status) status.textContent = 'Error: ' + e.message;
            }
        }

        async function updateAptitudePreview() {
            const parentPanel = els.aptitudePanel;
            const parentBars = els.aptitudeBars;
            const traineePanel = els.traineeAptPanel;
            const traineeTable = els.traineeAptTable;
            const vets = (selection.veterans || []).filter(v => v);
            const traineeCardId = selection.trainee ? (selection.trainee.id || selection.trainee.card_id) : null;

            // Hide trainee panel if no trainee selected
            if (!traineeCardId) {
                if (traineePanel) traineePanel.style.display = 'none';
                if (parentPanel) parentPanel.style.display = 'none';
                return;
            }
            // Hide parent bar chart if no parents selected
            if (vets.length === 0) {
                if (parentPanel) parentPanel.style.display = 'none';
            }
            try {
                const body = { parents: vets };
                if (traineeCardId) body.trainee_card_id = traineeCardId;
                const data = await apiJson('/api/advisor/aptitude-preview', {
                    method: 'POST',
                    body: JSON.stringify(body),
                    headers: { 'Content-Type': 'application/json' }
                });
                if (!data || !data.success) {
                    if (parentPanel) parentPanel.style.display = 'none';
                    if (traineePanel) traineePanel.style.display = 'none';
                    return;
                }
                const cats = (data.prediction || {}).categories || [];
                if (!cats.length) {
                    if (parentPanel) parentPanel.style.display = 'none';
                    if (traineePanel) traineePanel.style.display = 'none';
                    return;
                }

                // --- parent-section panel: keep bar chart (only when parents selected) ---
                if (parentPanel && parentBars && vets.length > 0) {
                    parentPanel.style.display = '';
                    const maxStars = 18;
                    parentBars.innerHTML = cats.map(c => {
                        const pct = Math.min(100, (c.stars / maxStars) * 100);
                        let cls = 'low';
                        if (c.stars >= 9) cls = 'high';
                        else if (c.stars >= 5) cls = 'mid';
                        const grade = c.grade || c.base_grade || '';
                        const gradeCls = grade && grade >= 'A' ? 'good' : 'bad';
                        return `<div class="aptitude-bar-row">
                            <span class="aptitude-bar-label">${escHtml(c.label)}</span>
                            <div class="aptitude-bar-track">
                                <div class="aptitude-bar-fill ${cls}" style="width:${pct}%"></div>
                            </div>
                            <span class="aptitude-bar-grade ${gradeCls}">${grade}</span>
                            <span class="aptitude-bar-stars">${c.stars}★</span>
                        </div>`;
                    }).join('');
                }

                // --- trainee panel: grade table (always when trainee is selected) ---
                if (traineePanel && traineeTable) {
                    traineePanel.style.display = '';
                    const order = data.prediction.category_order || [];
                    let html = '';
                    for (const [groupLabel, keys] of order) {
                        html += '<tr>';
                        html += `<td class="ag-row-label">${escHtml(groupLabel)}</td>`;
                        for (const key of keys) {
                            const c = cats.find(x => x.key === key);
                            if (!c) { html += '<td class="ag-cell">-</td>'; continue; }
                            const grade = c.grade || c.base_grade || '?';
                            const starStr = c.stars > 0 ? `+${c.stars}★` : '';
                            html += `<td class="ag-cell ag-grade-${grade}">${grade}<span class="ag-stars">${starStr}</span></td>`;
                        }
                        html += '</tr>';
                    }
                    traineeTable.innerHTML = html;
                }
            } catch (e) {
                if (parentPanel) parentPanel.style.display = 'none';
                if (traineePanel) traineePanel.style.display = 'none';
            }
        }

        // ==== FRIEND MANAGE (FOLLOW/UNFOLLOW) ===========================
        function bindFriendManage() {
            if (!els.friendIdInput || !els.friendPreviewBtn || !els.friendFollowBtn) return;
            els.friendPreviewBtn.addEventListener('click', previewFriendId);
            els.friendIdInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') previewFriendId();
            });
            els.friendFollowBtn.addEventListener('click', async () => {
                const vid = els.friendIdInput.value.trim();
                if (!vid) return;
                const action = els.friendFollowBtn.getAttribute('data-action') || 'follow';
                if (action === 'follow') await followFriendId(Number(vid));
                else await unfollowFriendId(Number(vid));
            });
        }

        let previewedFriendId = null;

        async function previewFriendId() {
            const vid = els.friendIdInput.value.trim();
            if (!vid || !Number(vid)) return;
            previewedFriendId = Number(vid);
            els.friendPreviewPanel.innerHTML = '<div class="friend-preview-loading">Loading...</div>';
            els.friendFollowBtn.disabled = true;
            try {
                const data = await apiJson('/api/friends/raw');
                if (data && data.success) {
                    const isFollowing = (dashData?.friends || []).some(f => Number(f.viewer_id) === Number(vid));
                    els.friendFollowBtn.disabled = false;
                    els.friendFollowBtn.textContent = isFollowing ? 'Unfollow' : 'Follow';
                    els.friendFollowBtn.setAttribute('data-action', isFollowing ? 'unfollow' : 'follow');
                    els.friendPreviewPanel.innerHTML = `
                        <div class="friend-preview-card">
                            <img src="/api/images/10001.png" onerror="hideBrokenImage(this)">
                            <div>
                                <div class="friend-preview-title">User #${vid}</div>
                                <div class="friend-preview-meta">Click Follow to add</div>
                            </div>
                        </div>
                    `;
                }
            } catch (e) {
                els.friendPreviewPanel.innerHTML = `<div class="friend-preview-error">Error: ${e.message}</div>`;
            }
        }

        async function followFriendId(viewerId) {
            if (!viewerId) return;
            els.friendManageStatus.textContent = 'Following...';
            try {
                const data = await apiJson('/api/friends/follow', {
                    method: 'POST',
                    body: JSON.stringify({ viewer_id: viewerId }),
                    headers: { 'Content-Type': 'application/json' }
                });
                if (data && data.success) {
                    els.friendManageStatus.textContent = 'Followed successfully';
                    els.friendIdInput.value = '';
                    els.friendPreviewPanel.innerHTML = '';
                    els.friendFollowBtn.disabled = true;
                    loadFriends(true);
                    renderFriendManageList();
                } else {
                    els.friendManageStatus.textContent = 'Failed: ' + (data?.detail || 'unknown');
                }
            } catch (e) {
                els.friendManageStatus.textContent = 'Error: ' + e.message;
            }
        }

        async function unfollowFriendId(viewerId) {
            if (!viewerId) return;
            els.friendManageStatus.textContent = 'Unfollowing...';
            try {
                const data = await apiJson('/api/friends/unfollow', {
                    method: 'POST',
                    body: JSON.stringify({ viewer_id: viewerId }),
                    headers: { 'Content-Type': 'application/json' }
                });
                if (data && data.success) {
                    els.friendManageStatus.textContent = 'Unfollowed successfully';
                    els.friendIdInput.value = '';
                    els.friendPreviewPanel.innerHTML = '';
                    els.friendFollowBtn.disabled = true;
                    loadFriends(true);
                    renderFriendManageList();
                } else {
                    els.friendManageStatus.textContent = 'Failed: ' + (data?.detail || 'unknown');
                }
            } catch (e) {
                els.friendManageStatus.textContent = 'Error: ' + e.message;
            }
        }

        function renderFriendManageList() {
            const container = els.friendManageList;
            if (!container) return;
            const friends = (dashData?.friends || []).filter(f => Number(f.friend_state || 0) >= 2);
            if (!friends.length) {
                container.innerHTML = '';
                return;
            }
            let html = '<div class="friend-follow-list-title">FOLLOWING (' + friends.length + ')</div>';
            friends.forEach(f => {
                const state = Number(f.friend_state || 0);
                const stateLabel = state >= 3 ? 'Mutual' : 'Following';
                const stateClass = 'friend-follow-label';
                html += `<div class="friend-follow-entry">
                    <img src="/api/images/${f.support_card_id || '10001'}.png" onerror="hideBrokenImage(this)">
                    <div>
                        <div style="font-weight:800;color:var(--text-main)">${f.support_name || 'Unknown'}</div>
                        <div style="font-size:0.65rem;color:var(--text-muted)">${f.name || ''} · ${f.viewer_id || ''}</div>
                        <span class="${stateClass}" data-state="${f.friend_state}">${stateLabel}</span>
                    </div>
                    <button class="btn btn-sm friend-manage-unfollow" data-viewer-id="${f.viewer_id}" type="button">Unfollow</button>
                </div>`;
            });
            container.innerHTML = html;
            container.querySelectorAll('.friend-manage-unfollow').forEach(btn => {
                btn.addEventListener('click', () => unfollowFriendId(Number(btn.getAttribute('data-viewer-id'))));
            });
        }

        // ==== FRIEND VETERANS ===========================================
        const VET_RANK_LABELS = {
            1:'G',2:'G+',3:'F',4:'F+',5:'E',6:'E+',7:'D',8:'D+',
            9:'C',10:'C+',11:'B',12:'B+',13:'A',14:'A+',15:'S',16:'S+',
            17:'SS',18:'SS+',19:'UG',20:'UG+',21:'UF',22:'UF+',23:'UE',24:'UE+',
            25:'UD',26:'UD+',27:'UC',28:'UC+',29:'UB',30:'UB+',31:'UA',32:'UA+',33:'US',34:'US+',
        };
        const VET_SCENARIO_NAMES = {1:'URA',2:'Aoharu',3:'MANT',4:'Trailblazer',5:'Grand Live',6:'Grand Masters',7:"L'Arc",8:'UAF',9:'Daily',10:'Pretty Derby',11:'Mecha'};

        function rankLabel(id) { return VET_RANK_LABELS[id] || (id ? 'R' + id : ''); }
        function rankTier(id) {
            if (!id) return 'low';
            if (id <= 8) return 'low';
            if (id <= 12) return 'mid';
            if (id <= 18) return 'high';
            return 'elite';
        }

        function renderVetStats(v) {
            const labels = ['SPD','STA','PWR','GTS','WIT'];
            const vals = [v.speed||0, v.stamina||0, v.power||0, v.guts||0, v.wiz||0];
            return '<div class="vet-stats">' + vals.map((val, i) =>
                '<div class="vet-stat"><div class="vet-stat-label">' + labels[i] + '</div><div class="vet-stat-val">' + val + '</div></div>'
            ).join('') + '</div>';
        }

        function renderVetFactors(v) {
            const factors = v.factors || [];
            if (!factors.length) return '';
            return '<div class="vet-factors">' + factors.map(f =>
                '<span class="vet-factor">' + escapeHtml(f.name || '?') + ' <span class="vet-factor-star">' + '★'.repeat(Math.min(f.stars||1,3)) + '</span></span>'
            ).join('') + '</div>';
        }

        function renderVetParents(v) {
            const ids = v.parent_card_ids || [];
            if (!ids.length) return '';
            return '<div class="vet-parents" title="Direct parents">' + ids.map(cid =>
                '<img class="vet-parent-portrait" src="/api/images/' + cid + '.png" onerror="hideBrokenImage(this)" alt="' + cid + '">'
            ).join('') + '</div>';
        }

        function renderSupportDeckStrip(cards) {
            if (!cards || !cards.length) return '';
            return '<div class="vet-deck-strip">' + cards.map(c =>
                '<img class="vet-deck-portrait" src="/api/images/' + (c.card_id || c.support_card_id || '10001') + '.png" onerror="hideBrokenImage(this)" title="' + escapeHtml(c.name || '') + '">'
            ).join('') + '</div>';
        }

        function friendCardHtml(v, idx) {
            const rankId = v.rank || 0;
            const label = rankLabel(rankId);
            const tier = rankTier(rankId);
            const scenarioName = VET_SCENARIO_NAMES[v.scenario_id] || 'Scenario ' + v.scenario_id;
            const deckCards = v.deck_support_cards || [];
            const selected = (selection.veterans || []).some(sv => String(sv.viewer_id) === String(v.viewer_id) && String(sv.trained_chara_id) === String(v.trained_chara_id));
            return '<div class="vet-card selectable' + (selected ? ' selected' : '') + '" data-vet-idx="' + idx + '" data-vet-key="' + (v.viewer_id + ':' + v.trained_chara_id) + '">' +
                '<img class="vet-portrait" src="/api/images/' + (v.card_id || '10001') + '.png" onerror="hideBrokenImage(this)">' +
                '<div>' +
                '<div class="vet-header">' +
                '<span class="vet-name">' + escapeHtml(v.chara_name || '') + '</span>' +
                '<span class="vet-rank-badge vet-rank-' + tier + '">' + label + '</span>' +
                '<span style="font-size:0.6rem;color:var(--text-muted)">' + scenarioName + '</span>' +
                '</div>' +
                renderVetStats(v) +
                '<div class="vet-info-row">' +
                '<span>' + escapeHtml(v.trainer_name || '') + '</span>' +
                '<span>#ID ' + v.trained_chara_id + '</span>' +
                '<span>' + (v.wins || 0) + ' wins</span>' +
                '</div>' +
                renderVetParents(v) +
                renderVetFactors(v) +
                renderSupportDeckStrip(deckCards) +
                '</div></div>';
        }

        async function loadFriendVeterans(refresh = false) {
            if (!els.friendVetGrid) return;
            els.friendVetStatus.textContent = 'Loading...';
            try {
                let data;
                if (refresh) {
                    data = await apiJson('/api/career/friends', {
                        method: 'POST',
                        body: JSON.stringify({ exclude_viewer_ids: [], force_refresh: true }),
                        headers: { 'Content-Type': 'application/json' }
                    });
                    if (data && data.success) dashData = data;
                } else {
                    data = await apiJson('/api/friends/veterans');
                }
                if (data && data.success) {
                    const vets = data.veterans || [];
                    els.friendVetCount.textContent = '(' + vets.length + ')';
                    els.friendVetStatus.textContent = vets.length + ' veterans loaded';
                    state._veterans = vets;
                    renderFriendVeterans();
                } else {
                    els.friendVetStatus.textContent = 'No data — call /api/career/friends first';
                }
            } catch (e) {
                els.friendVetStatus.textContent = 'Error: ' + e.message;
            }
        }

        function renderFriendVeterans() {
            const grid = els.friendVetGrid;
            if (!grid) return;
            let vets = state._veterans || [];
            const q = (els.friendVetSearch?.value || '').toLowerCase();
            const rankFilter = els.friendVetRank?.value || '';
            if (q) vets = vets.filter(v =>
                (v.chara_name || '').toLowerCase().includes(q) ||
                String(v.card_id || '').includes(q) ||
                (v.trainer_name || '').toLowerCase().includes(q)
            );
            if (rankFilter) {
                const rankLabels = rankFilter.split(' — ');
                vets = vets.filter(v => {
                    const label = rankLabel(v.rank || 0);
                    return rankLabels.some(r => label.startsWith(r));
                });
            }
            grid.innerHTML = vets.map((v, i) => friendCardHtml(v, i)).join('');
            if (!vets.length) grid.innerHTML = '<div class="vet-count-msg">No veterans match</div>';
            bindVetHandlers();

            const sparkToggle = els.friendVetSparkToggle;
            const sparkDrawer = els.friendVetSparkDrawer;
            if (sparkToggle && sparkDrawer) {
                if (sparkToggle.checked) {
                    const totalRows = new Set(vets.map(v => v.viewer_id + ':' + v.trained_chara_id)).size;
                    sparkDrawer.style.display = 'block';
                    sparkDrawer.innerHTML = '<div class="vet-count-msg">Veterans: ' + vets.length + ' total, ' + totalRows + ' unique.</div>';
                } else {
                    sparkDrawer.style.display = 'none';
                }
            }
        }

        function syncFriendVeteranSelection() {
            // Stub — could auto-select a veteran from filtered list if needed
        }

        function selectVeteran(idx, element) {
            const vets = state._veterans || [];
            const vet = vets[idx];
            if (!vet) return;
            if (element.classList.contains('selected')) {
                element.classList.remove('selected');
                selection.veterans = selection.veterans.filter(sv =>
                    !(String(sv.viewer_id) === String(vet.viewer_id) && String(sv.trained_chara_id) === String(vet.trained_chara_id))
                );
            } else if (selection.veterans.length < 2) {
                // Check not already selected
                const already = selection.veterans.some(sv =>
                    String(sv.viewer_id) === String(vet.viewer_id) && String(sv.trained_chara_id) === String(vet.trained_chara_id)
                );
                if (!already) {
                    const vetFull = vet.viewer_id ? {
                        viewer_id: Number(vet.viewer_id),
                        trained_chara_id: Number(vet.trained_chara_id),
                        card_id: Number(vet.card_id || 0),
                    } : null;
                    if (vetFull) {
                        selection.veterans.push(vetFull);
                        element.classList.add('selected');
                    }
                }
            }
            updateVetSelectability();
            renderTeamPanel();
            syncSelectionToServer();
        }

        function bindVetHandlers() {
            document.querySelectorAll('#friend-vet-grid .vet-card').forEach(el => {
                el.addEventListener('click', () => {
                    const idx = parseInt(el.dataset.vetIdx, 10);
                    if (!isNaN(idx)) selectVeteran(idx, el);
                });
            });
        }

        // Refresh veterans also when friends are refreshed
        const origLoadFriends = loadFriends;
        loadFriends = async function loadFriendsPatched(refresh) {
            await origLoadFriends(refresh);
            if (dashData && dashData.friendVeterans) {
                state._veterans = dashData.friendVeterans;
                renderFriendVeterans();
                renderAdvisorPanel();
                updateAdvisorRecommendations();
            }
        };

        // Patch renderFriends to also refresh manage list
        const origRenderFriends = renderFriends;
        renderFriends = function renderFriendsPatched() {
            origRenderFriends();
            renderFriendManageList();
        };
    })();
