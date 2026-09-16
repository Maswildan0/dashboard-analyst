/* ==================================================================
 * Manual revenue data management — SHARED by Data Revenue, Data TF,
 * Data NTF Research and Data NTF Project.
 *
 * The page only supplies context (mode, allowed revenue types, period, its
 * lock state and the user's rights); every control, dialog and request lives
 * here. Cascading master data is always fetched from the backend — no PP or
 * account list is hardcoded (§6).
 *
 * Optimization rules honoured:
 *   - the row is never removed before the server confirms (§52);
 *   - the submit button is disabled while a request is in flight so a double
 *     click cannot create two records (§53);
 *   - errors keep the dialog open with the message and the offending field.
 * ================================================================== */
(function () {
    'use strict';

    const root = document.getElementById('rm-root');
    if (!root) return;

    const CFG = {
        pageMode: root.dataset.pageMode || '',
        allowedTypes: (root.dataset.allowedTypes || '').split(',').filter(Boolean),
        lockedType: root.dataset.lockedType || '',
        period: root.dataset.period || '',
        closed: root.dataset.periodClosed === '1',
        can: {
            create: root.dataset.canCreate === '1',
            edit: root.dataset.canEdit === '1',
            void: root.dataset.canVoid === '1',
            restore: root.dataset.canRestore === '1',
            adjust: root.dataset.canAdjust === '1',
            audit: root.dataset.canAudit === '1',
        },
    };

    const CSRF = (root.querySelector('input[name=csrfmiddlewaretoken]') || {}).value || '';
    const URLS = {
        create: root.dataset.urlCreate || '/dashboard/revenue/manual/create/',
        edit: (id) => `/dashboard/revenue/manual/${id}/edit/`,
        projectEdit: (id) => `/dashboard/revenue/manual/project/${id}/edit/`,
        void: (id) => `/dashboard/revenue/manual/${id}/void/`,
        restore: (id) => `/dashboard/revenue/manual/${id}/restore/`,
        adjustment: root.dataset.urlAdjust || '/dashboard/revenue/manual/adjustment/',
        entries: root.dataset.urlEntries || '/dashboard/revenue/manual/entries/',
        history: root.dataset.urlHistory || '/dashboard/revenue/manual/history/',
        deleted: root.dataset.urlDeleted || '/dashboard/revenue/manual/deleted/',
        optPps: root.dataset.urlOptPps || '/dashboard/revenue/manual/options/pps/',
        optAccounts: root.dataset.urlOptAccounts || '/dashboard/revenue/manual/options/accounts/',
        optProjects: root.dataset.urlOptProjects || '/dashboard/revenue/manual/options/projects/',
        optLedger: root.dataset.urlOptLedger || '/dashboard/revenue/manual/options/ledger/',
    };

    /* ------------------------------------------------------------------ *
     * Small helpers
     * ------------------------------------------------------------------ */
    const $ = (sel, scope) => (scope || document).querySelector(sel);
    const $$ = (sel, scope) => Array.prototype.slice.call((scope || document).querySelectorAll(sel));

    const MONTHS = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
        'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];

    function rupiah(value) {
        const n = Number(String(value == null ? 0 : value).replace(/[^0-9.-]/g, ''));
        if (!isFinite(n)) return 'Rp0';
        return 'Rp' + Math.round(n).toLocaleString('id-ID');
    }

    function todayISO() {
        const d = new Date();
        const p = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    }

    function toast(message, kind) {
        let host = document.querySelector('.rm-toasts');
        if (!host) {
            host = document.createElement('div');
            host.className = 'rm-toasts';
            document.body.appendChild(host);
        }
        const el = document.createElement('div');
        el.className = 'rm-toast ' + (kind === 'error' ? 'rm-toast-err' : 'rm-toast-ok');
        el.innerHTML = `<i class="bi ${kind === 'error' ? 'bi-exclamation-triangle' : 'bi-check-circle'}"></i><span></span>`;
        el.lastElementChild.textContent = message;
        host.appendChild(el);
        setTimeout(() => el.remove(), 5200);
    }

    async function post(url, payload) {
        const body = new URLSearchParams(payload);
        if (CSRF) body.append('csrfmiddlewaretoken', CSRF);
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': CSRF, 'X-Requested-With': 'XMLHttpRequest' },
            body,
            credentials: 'same-origin',
        });
        let data = {};
        try { data = await res.json(); } catch (e) { data = {}; }
        if (!res.ok || data.ok === false) {
            const err = new Error(data.message || `Permintaan gagal (HTTP ${res.status}).`);
            err.field = data.field || null;
            throw err;
        }
        return data;
    }

    async function getJSON(url, params) {
        const qs = params ? '?' + new URLSearchParams(params).toString() : '';
        const res = await fetch(url + qs, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin',
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    async function getHTML(url, params) {
        const qs = params ? '?' + new URLSearchParams(params).toString() : '';
        const res = await fetch(url + qs, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin',
        });
        const data = await res.json();
        if (!res.ok || data.ok === false) throw new Error(data.message || `HTTP ${res.status}`);
        return data;
    }

    function setOptions(select, items, placeholder, labelOf) {
        select.innerHTML = '';
        const ph = document.createElement('option');
        ph.value = '';
        ph.textContent = placeholder;
        select.appendChild(ph);
        items.forEach((item) => {
            const opt = document.createElement('option');
            opt.value = item.value;
            opt.textContent = labelOf ? labelOf(item) : item.label;
            if (item.name !== undefined) opt.dataset.name = item.name;
            if (item.value_amount !== undefined) opt.dataset.valueAmount = item.value_amount;
            if (item.source_type !== undefined) opt.dataset.sourceType = item.source_type;
            if (item.type !== undefined) opt.dataset.type = item.type;
            select.appendChild(opt);
        });
        select.disabled = items.length === 0;
    }

    /* ------------------------------------------------------------------ *
     * Modal plumbing
     * ------------------------------------------------------------------ */
    function openModal(name) {
        const modal = $(`[data-rm-modal="${name}"]`);
        if (!modal) return null;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        return modal;
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.hidden = true;
        if (!$$('.rm-modal').some((m) => !m.hidden)) document.body.style.overflow = '';
    }

    function resetForm(form) {
        if (!form) return;
        form.reset();
        $$('.rm-input.is-invalid', form).forEach((el) => el.classList.remove('is-invalid'));
        const err = $('[data-rm-error]', form);
        if (err) { err.hidden = true; err.textContent = ''; err.classList.remove('rm-form-ok'); }
        $$('[data-rm-other-wrap]', form).forEach((el) => { el.hidden = true; });
        busy(form, false);
    }

    function busy(form, state, label) {
        const btn = $('[data-rm-submit]', form);
        if (!btn) return;
        btn.disabled = state;
        const spin = $('.rm-spinner', btn);
        if (spin) spin.hidden = !state;
        const text = $('[data-rm-submit-text]', btn);
        if (text && label) text.textContent = label;
    }

    function showError(form, message, field) {
        const err = $('[data-rm-error]', form);
        if (err) {
            err.hidden = false;
            err.classList.remove('rm-form-ok');
            err.textContent = message;
        }
        if (field) {
            const input = form.querySelector(`[name="${field}"]`);
            if (input) {
                input.classList.add('is-invalid');
                input.focus();
            }
        }
        toast(message, 'error');
    }

    function recap(form, rows) {
        const host = $('[data-rm-recap]', form);
        if (!host) return;
        host.innerHTML = rows.map(([label, value]) =>
            `<div class="rm-recap-item"><span>${label}</span><b>${value}</b></div>`).join('');
    }

    document.addEventListener('click', (ev) => {
        const closer = ev.target.closest('[data-rm-close]');
        if (closer) {
            closeModal(closer.closest('.rm-modal'));
            return;
        }
        if (ev.target.classList && ev.target.classList.contains('rm-modal')) closeModal(ev.target);
    });
    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') {
            const open = $$('.rm-modal').filter((m) => !m.hidden);
            if (open.length) closeModal(open[open.length - 1]);
        }
    });

    /* ------------------------------------------------------------------ *
     * Cascading master data (§6). Organization -> PP, Revenue Type -> Account.
     * Every option comes from the backend; nothing is hardcoded here.
     * ------------------------------------------------------------------ */
    async function loadPps(form, keepValue) {
        const org = $('[data-rm-org]', form);
        const pp = $('[data-rm-pp]', form);
        if (!org || !pp) return;
        pp.disabled = true;
        if (!org.value) {
            setOptions(pp, [], '— Pilih Organization dahulu —');
            return;
        }
        try {
            const items = await getJSON(URLS.optPps, { org: org.value });
            setOptions(pp, items, '— Pilih Kode PP —');
            if (keepValue) pp.value = keepValue;
        } catch (e) {
            setOptions(pp, [], '— Gagal memuat PP —');
        }
    }

    async function loadAccounts(form, keepValue) {
        const type = $('[data-rm-type]', form);
        const acc = $('[data-rm-account]', form);
        if (!type || !acc) return;
        acc.disabled = true;
        if (!type.value) {
            setOptions(acc, [], '— Pilih Jenis Revenue dahulu —');
            return;
        }
        try {
            const items = await getJSON(URLS.optAccounts, { type: type.value });
            setOptions(acc, items, '— Pilih Revenue Account —');
            if (keepValue) acc.value = keepValue;
        } catch (e) {
            setOptions(acc, [], '— Gagal memuat akun —');
        }
    }

    async function loadProjects(form, keepValue) {
        const pp = $('[data-rm-pp]', form);
        const acc = $('[data-rm-account]', form);
        const type = $('[data-rm-type]', form);
        const proj = $('[data-rm-project]', form);
        if (!proj) return;
        if (!pp || !pp.value || !acc || !acc.value) {
            setOptions(proj, [], '— Pilih PP & Akun dahulu —');
            return;
        }
        try {
            const items = await getJSON(URLS.optProjects, {
                pp: pp.value, account: acc.value, type: type ? type.value : '',
            });
            setOptions(proj, items, '— Pilih Project —',
                (i) => `${i.number} · ${i.name || '(tanpa nama)'}`.trim());
            if (keepValue) proj.value = keepValue;
        } catch (e) {
            setOptions(proj, [], '— Gagal memuat project —');
        }
    }

    async function loadLedger(form) {
        const pp = $('[data-rm-pp]', form);
        const acc = $('[data-rm-account]', form);
        const ledger = $('[data-rm-ledger]', form);
        if (!ledger) return;
        if (!pp || !pp.value || !acc || !acc.value) {
            setOptions(ledger, [], '— Pilih PP & Akun dahulu —');
            return;
        }
        try {
            const items = await getJSON(URLS.optLedger, { pp: pp.value, account: acc.value });
            setOptions(ledger, items, '— Tanpa referensi —');
        } catch (e) {
            setOptions(ledger, [], '— Gagal memuat transaksi sumber —');
        }
    }

    /* Period options: the years/months the dashboard already exposes, so the
       dialog can never target a period the tables do not show. */
    function periodChoices(form) {
        const select = $('[data-rm-period-select]', form);
        if (!select || select.options.length) return;
        const years = $$('[data-ms-name="tahun"] input[type=checkbox]')
            .map((i) => i.value).filter((v) => /^\d{4}$/.test(v));
        const months = $$('[data-ms-name="bulan"] input[type=checkbox]')
            .map((i) => i.value).filter((v) => /^\d{1,2}$/.test(v));
        const hdr = [];
        (years.length ? years : [String(new Date().getFullYear())]).forEach((y) => {
            (months.length ? months : Array.from({ length: 12 }, (_, i) => String(i + 1)))
                .forEach((m) => hdr.push({ value: `${y}-${String(m).padStart(2, '0')}`, label: `${MONTHS[Number(m) - 1]} ${y}` }));
        });
        hdr.sort((a, b) => (a.value < b.value ? 1 : -1));
        select.innerHTML = '';
        hdr.forEach((p) => {
            const opt = document.createElement('option');
            opt.value = p.value;
            opt.textContent = p.label;
            select.appendChild(opt);
        });
        if (CFG.period) select.value = CFG.period;
        updatePeriodHint(form);
    }

    function updatePeriodHint(form) {
        const select = $('[data-rm-period-select]', form);
        const hint = $('[data-rm-period-hint]', form);
        if (!select || !hint) return;
        const closed = select.value && select.value !== CFG.period && CFG.closed;
        const isClosed = select.value === CFG.period && CFG.closed;
        hint.textContent = isClosed
            ? 'Periode sudah ditutup. Data hanya dapat ditambahkan pada periode OPEN.'
            : (closed ? 'Periksa status periode sebelum menyimpan.' : '');
        hint.classList.toggle('rm-hint-error', isClosed);
    }

    function typeChoices(form) {
        const select = $('[data-rm-type]', form);
        if (!select || select.options.length) return;
        const labels = { TF: 'TF', NTF_RESEARCH: 'NTF Research', NTF_PROJECT: 'NTF Project' };
        select.innerHTML = '';
        CFG.allowedTypes.forEach((code) => {
            const opt = document.createElement('option');
            opt.value = code;
            opt.textContent = labels[code] || code;
            select.appendChild(opt);
        });
        const hint = $('[data-rm-type-hint]', form);
        if (hint && CFG.lockedType) hint.textContent = 'Jenis Revenue dikunci oleh halaman ini.';
        if (CFG.lockedType) {
            select.value = CFG.lockedType;
            select.disabled = true;
            // A disabled select is not submitted: keep the value in a hidden field.
            let hidden = form.querySelector('input[type=hidden][name=revenue_type]');
            if (!hidden) {
                hidden = document.createElement('input');
                hidden.type = 'hidden';
                hidden.name = 'revenue_type';
                form.appendChild(hidden);
            }
            hidden.value = CFG.lockedType;
        } else if (CFG.allowedTypes.length === 1) {
            select.value = CFG.allowedTypes[0];
        }
    }

    function orgChoices(form) {
        const select = $('[data-rm-org]', form);
        if (!select) return;
        const items = $$('[data-ms-name="org"] input[type=checkbox]')
            .filter((i) => /^\d+$/.test(i.value))
            .map((i) => ({
                value: i.value,
                label: (i.closest('label').querySelector('.df-option-text') || {}).textContent || i.value,
            }));
        setOptions(select, items, '— Pilih Organization —');
    }

    /* ------------------------------------------------------------------ *
     * Create form
     * ------------------------------------------------------------------ */
    const createModal = $('[data-rm-modal="create"]');
    const createForm = createModal ? $('[data-rm-form="create"]', createModal) : null;

    function prepareCreate() {
        if (!createForm) return;
        resetForm(createForm);
        periodChoices(createForm);
        typeChoices(createForm);
        orgChoices(createForm);
        setOptions($('[data-rm-pp]', createForm), [], '— Pilih Organization dahulu —');
        setOptions($('[data-rm-account]', createForm), [], '— Pilih Jenis Revenue dahulu —');
        setOptions($('[data-rm-project]', createForm), [], '— Pilih PP & Akun dahulu —');
        $('[data-rm-project-row]', createForm).hidden = true;
        $('[data-rm-new-project]', createForm).hidden = false;
        const dateInput = $('[name=transaction_date]', createForm);
        if (dateInput && !dateInput.value) dateInput.value = todayISO();
        setMode('new');
    }

    function setMode(mode) {
        if (!createForm) return;
        $$('[data-rm-mode]', createForm).forEach((btn) => {
            const active = btn.dataset.rmMode === mode;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        const existing = mode === 'existing';
        $('[data-rm-project-row]', createForm).hidden = !existing;
        $('[data-rm-new-project]', createForm).hidden = existing;
        createForm.dataset.mode = mode;
    }

    $$('[data-rm-mode]').forEach((btn) => {
        btn.addEventListener('click', () => setMode(btn.dataset.rmMode));
    });

    /* Prefill the form from a table row so "Tambah Pengakuan" and
       "Koreksi / Adjustment" start on the right object (§8, §27). */
    function prefillFromRow(form, dataset) {
        if (!dataset) return;
        const set = (name, value) => {
            const el = form.querySelector(`[name="${name}"]`);
            if (el && value !== undefined && value !== null && value !== '') el.value = value;
        };
        set('revenue_type', dataset.rmType);
        set('organization', dataset.rmOrg);
        set('pp', dataset.rmPp);
        set('revenue_account', dataset.rmAccount);
    }

    function rowDataset(el) {
        const row = el && el.closest('.rev-row-expand');
        return row ? row.dataset : null;
    }

    /* One click dispatcher for every action control. It runs BEFORE the row
       handler (capture phase) and stops propagation whenever the click landed
       inside a row menu, so working the menu never toggles the expand panel. */
    document.addEventListener('click', async (ev) => {
        if (ev.target.closest('[data-rm-rowmenu]')) {
            handleRowMenu(ev);
            ev.stopPropagation();
        } else {
            closeRowMenus();
        }
        const opener = ev.target.closest('[data-rm-open="create"]');
        if (opener) {
            if (CFG.closed) { toast('Periode sudah ditutup.', 'error'); return; }
            prepareCreate();
            prefillFromRow(createForm, rowDataset(opener));
            await refreshCascade(createForm);
            openModal('create');
            return;
        }
        const openAdj = ev.target.closest('[data-rm-open="adjustment"]');
        if (openAdj) {
            if (CFG.closed) { toast('Periode sudah ditutup.', 'error'); return; }
            await openAdjustment(null, null);
            return;
        }
        const addRec = ev.target.closest('[data-rm-add-recognition]');
        if (addRec) {
            if (CFG.closed) { toast('Periode sudah ditutup.', 'error'); return; }
            prepareCreate();
            setMode('existing');
            const pid = addRec.dataset.rmAddRecognition;
            const row = addRec.closest('.rev-row-expand');
            await refreshCascade(createForm);
            if (row) prefillFromRow(createForm, row.dataset);
            await loadProjects(createForm, pid);
            openModal('create');
            return;
        }
        const editProject = ev.target.closest('[data-rm-edit-project]');
        if (editProject) {
            if (CFG.closed) { toast('Periode sudah ditutup.', 'error'); return; }
            await openManage(editProject.dataset.rmEditProject);
            return;
        }
        const adjust = ev.target.closest('[data-rm-adjust-project]');
        if (adjust) {
            if (CFG.closed) { toast('Periode sudah ditutup.', 'error'); return; }
            await openAdjustment(adjust.dataset.rmAdjustProject, adjust.closest('.rev-row-expand'));
            return;
        }
        const historyBtn = ev.target.closest('[data-rm-history-project]');
        if (historyBtn) {
            await openHistory(historyBtn.dataset.rmHistoryProject, false);
            return;
        }
        const voidBtn = ev.target.closest('[data-rm-void-project]');
        if (voidBtn) {
            await openVoidProject(voidBtn.dataset.rmVoidProject);
            return;
        }
        // --- actions of one transaction inside the expanded history panel ---
        const histEdit = ev.target.closest('[data-rm-edit-entry-from-history]');
        if (histEdit) {
            await openEntryEditor(histEdit.dataset.rmEditEntryFromHistory, histEdit);
            return;
        }
        const histAudit = ev.target.closest('[data-rm-history-entry]');
        if (histAudit) {
            await openEntryHistory(histAudit.dataset.rmHistoryEntry, histAudit);
            return;
        }
        const detail = ev.target.closest('[data-rm-detail]');
        if (detail) {
            const row = detail.closest('.rev-row-expand');
            if (row) row.click();
            return;
        }
    }, true);

    /** Project id owning the fragment `el` sits in (the expanded panel). */
    function projectIdOf(el) {
        const panel = el.closest('[data-project-panel]');
        if (panel) return panel.dataset.projectPanel;
        const head = el.closest('[data-rm-recognitions]');
        return head ? head.dataset.rmRecognitions : null;
    }

    /** Load (once per project) the manual entries the row menus act on. */
    async function ensureEntries(projectId) {
        if (!projectId) return [];
        if (window.__rmEntriesProject === projectId && window.__rmManageEntries) {
            return window.__rmManageEntries;
        }
        const data = await getJSON(URLS.entries, { project: projectId });
        window.__rmEntriesProject = projectId;
        window.__rmManageEntries = data.entries || [];
        return window.__rmManageEntries;
    }

    async function openEntryEditor(entryId, el) {
        if (!txnForm) return;
        const entries = await ensureEntries(projectIdOf(el));
        const entry = entries.find((e) => String(e.id) === String(entryId));
        if (!entry) { toast('Data transaksi tidak ditemukan.', 'error'); return; }
        resetForm(txnForm);
        $('[data-rm-txn-id]', txnForm).value = entry.id;
        $('[name=transaction_date]', txnForm).value = entry.date || '';
        $('[name=amount]', txnForm).value = entry.amount || '';
        $('[name=evidence_number]', txnForm).value = entry.evidence_number || '';
        $('[name=document_number]', txnForm).value = entry.document_number || '';
        $('[name=description]', txnForm).value = entry.description || '';
        openModal('txn-edit');
    }

    async function openEntryHistory(entryId, el) {
        const modal = openModal('history');
        const body = $('[data-rm-history-body]', modal);
        $('[data-rm-history-title]', modal).textContent = 'Riwayat Perubahan';
        $('[data-rm-history-sub]', modal).textContent =
            'Jejak audit transaksi ini. Tidak dapat diubah.';
        body.innerHTML = '<div class="rm-empty">Memuat riwayat perubahan…</div>';
        try {
            const data = await getHTML(URLS.history, { entry: entryId });
            body.innerHTML = data.html;
        } catch (e) {
            body.innerHTML = '<div class="rm-empty"></div>';
            $('.rm-empty', body).textContent = e.message;
        }
    }

    function handleRowMenu(ev) {
        const toggle = ev.target.closest('[data-rm-rowmenu-toggle]');
        const mine = toggle ? toggle.closest('[data-rm-rowmenu]') : null;
        $$('.rm-rowmenu-panel').forEach((panel) => {
            if (panel.closest('[data-rm-rowmenu]') !== mine) panel.hidden = true;
        });
        if (!toggle) return;
        const panel = $('.rm-rowmenu-panel', mine);
        if (!panel) return;
        panel.hidden = !panel.hidden;
        toggle.setAttribute('aria-expanded', panel.hidden ? 'false' : 'true');
    }

    function closeRowMenus() {
        $$('.rm-rowmenu-panel').forEach((panel) => { panel.hidden = true; });
    }

    async function refreshCascade(form) {
        const type = $('[data-rm-type]', form);
        const org = $('[data-rm-org]', form);
        if (type && type.value) await loadAccounts(form);
        if (org && org.value) await loadPps(form);
    }

    if (createForm) {
        const org = $('[data-rm-org]', createForm);
        const type = $('[data-rm-type]', createForm);
        const pp = $('[data-rm-pp]', createForm);
        const acc = $('[data-rm-account]', createForm);
        const proj = $('[data-rm-project]', createForm);
        if (org) org.addEventListener('change', async () => { await loadPps(createForm); await loadProjects(createForm); });
        if (type) type.addEventListener('change', async () => { await loadAccounts(createForm); await loadProjects(createForm); });
        if (pp) pp.addEventListener('change', () => loadProjects(createForm));
        if (acc) acc.addEventListener('change', () => loadProjects(createForm));
        if (proj) proj.addEventListener('change', () => {
            const opt = proj.options[proj.selectedIndex];
            const hint = $('[data-rm-project-hint]', createForm);
            if (!opt || !hint) return;
            hint.textContent = opt.dataset.sourceType === 'MANUAL'
                ? 'Project manual: nama dan nilai proyek dapat diperbarui.'
                : 'Project dari data import: nama/nomor/nilai proyek tidak dapat diubah di sini.';
        });
        const periodSel = $('[data-rm-period-select]', createForm);
        if (periodSel) periodSel.addEventListener('change', () => updatePeriodHint(createForm));

        createForm.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const mode = createForm.dataset.mode || 'new';
            const payload = Object.fromEntries(new FormData(createForm).entries());
            if (mode === 'existing' && !payload.project) {
                showError(createForm, 'Pilih project existing terlebih dahulu.', 'project');
                return;
            }
            busy(createForm, true, 'Menyimpan…');
            try {
                const res = await post(URLS.create, payload);
                toast(res.message || 'Data manual berhasil disimpan.');
                closeModal(createModal);
                reloadPage();
            } catch (e) {
                showError(createForm, e.message, e.field);
            } finally {
                busy(createForm, false, 'Simpan');
            }
        });
    }

    /* ------------------------------------------------------------------ *
     * Adjustment dialog (§27, §28)
     * ------------------------------------------------------------------ */
    const adjustModal = $('[data-rm-modal="adjustment"]');
    const adjustForm = adjustModal ? $('[data-rm-form="adjustment"]', adjustModal) : null;

    async function openAdjustment(projectId, rowEl) {
        if (!adjustForm) return;
        resetForm(adjustForm);
        periodChoices(adjustForm);
        typeChoices(adjustForm);
        orgChoices(adjustForm);
        setOptions($('[data-rm-pp]', adjustForm), [], '— Pilih Organization dahulu —');
        setOptions($('[data-rm-account]', adjustForm), [], '— Pilih Jenis Revenue dahulu —');
        setOptions($('[data-rm-project]', adjustForm), [], '— Pilih PP & Akun dahulu —');
        setOptions($('[data-rm-ledger]', adjustForm), [], '— Pilih PP & Akun dahulu —');
        const dateInput = $('[name=transaction_date]', adjustForm);
        if (dateInput) dateInput.value = todayISO();
        if (rowEl) prefillFromRow(adjustForm, rowEl.dataset);
        await refreshCascade(adjustForm);
        if (projectId) await loadProjects(adjustForm, projectId);
        // The imported source must be chosen from real ledger rows, so the
        // reference list follows the PP + account of the row being corrected.
        await loadLedger(adjustForm);
        recap(adjustForm, [
            ['Sumber', 'Data import (SIMKUG / NTF)'],
            ['Perlakuan', 'Dibuat baris koreksi baru'],
        ]);
        openModal('adjustment');
    }

    if (adjustForm) {
        ['org', 'pp', 'account', 'type'].forEach((name) => {
            const el = adjustForm.querySelector(`[name="${name}"], [data-rm-${name === 'org' ? 'org' : name === 'pp' ? 'pp' : name === 'account' ? 'account' : 'type'}]`);
            if (!el) return;
            el.addEventListener('change', async () => {
                if (name === 'org') { await loadPps(adjustForm); }
                if (name === 'type') { await loadAccounts(adjustForm); }
                if (name === 'pp' || name === 'account' || name === 'type') {
                    await loadProjects(adjustForm);
                    await loadLedger(adjustForm);
                }
            });
        });
        adjustForm.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const payload = Object.fromEntries(new FormData(adjustForm).entries());
            // A correction always targets an existing object (§27); the server
            // enforces this too, the check here only saves a round trip.
            if (!payload.project) {
                showError(adjustForm,
                    'Pilih project/objek yang akan dikoreksi terlebih dahulu.', 'project');
                return;
            }
            busy(adjustForm, true, 'Menyimpan…');
            try {
                const res = await post(URLS.adjustment, payload);
                toast(res.message || 'Koreksi berhasil dicatat.');
                closeModal(adjustModal);
                reloadPage();
            } catch (e) {
                showError(adjustForm, e.message, e.field);
            } finally {
                busy(adjustForm, false, 'Simpan Koreksi');
            }
        });
    }

    /* ------------------------------------------------------------------ *
     * Void (soft delete) (§20, §21)
     * ------------------------------------------------------------------ */
    const voidModal = $('[data-rm-modal="void"]');
    const voidForm = voidModal ? $('[data-rm-form="void"]', voidModal) : null;
    const pickerModal = $('[data-rm-modal="history"]');
    let voidTargets = [];

    async function openVoidProject(projectId) {
        if (!voidForm) return;
        // A delete always targets ONE transaction, never a whole project: the
        // operator picks the exact POSTED row so a project with several
        // termin rows is not voided wholesale (§18).
        try {
            const data = await getJSON(URLS.entries, { project: projectId });
            voidTargets = (data.entries || []).filter((e) => e.can_void);
        } catch (e) {
            toast(e.message, 'error');
            return;
        }
        if (!voidTargets.length) {
            toast('Tidak ada data manual aktif yang dapat dihapus pada project ini.', 'error');
            return;
        }
        openVoidPicker();
    }

    function openVoidPicker() {
        // Reuses the history dialog shell as the transaction picker.
        const modal = openModal('history');
        $('[data-rm-history-title]', modal).textContent = 'Pilih Pengakuan yang Dihapus';
        $('[data-rm-history-sub]', modal).textContent =
            'Pilih transaksi yang akan dihapus. Riwayat perubahan tetap tersimpan.';
        const host = $('[data-rm-history-body]', modal);
        host.innerHTML = '';
        voidTargets.forEach((entry) => {
            const row = document.createElement('div');
            row.className = 'rm-tl-item';
            row.innerHTML = `
                <div class="rm-tl-marker rm-tl-delete"></div>
                <div class="rm-tl-body">
                    <div class="rm-tl-head">
                        <span class="rm-tl-date"></span>
                        <span class="rm-tl-user"></span>
                    </div>
                    <div class="rm-tl-changes"><div class="rm-tl-change">
                        <span class="rm-tl-label">Nominal</span><span class="rm-tl-after"></span>
                    </div></div>
                </div>
                <button type="button" class="rm-btn rm-btn-mini rm-btn-danger" data-rm-void-entry="${entry.id}">Hapus</button>`;
            row.querySelector('.rm-tl-date').textContent = entry.date_text;
            row.querySelector('.rm-tl-user').textContent = entry.account;
            row.querySelector('.rm-tl-after').textContent = entry.amount_text;
            host.appendChild(row);
        });
    }

    document.addEventListener('click', async (ev) => {
        const btn = ev.target.closest('[data-rm-void-entry]');
        if (!btn) return;
        const id = btn.dataset.rmVoidEntry;
        // The same button is emitted by the void picker, the manage drawer and
        // the expanded history panel, so the row is resolved from whichever
        // list is loaded — fetching the project's entries when none is.
        let entry = voidTargets.find((t) => String(t.id) === id)
            || (window.__rmManageEntries || []).find((e) => String(e.id) === id);
        if (!entry) {
            try {
                const entries = await ensureEntries(projectIdOf(btn));
                entry = entries.find((e) => String(e.id) === id);
            } catch (e) {
                toast(e.message, 'error');
            }
        }
        if (!entry) { toast('Data transaksi tidak ditemukan.', 'error'); return; }
        if (!voidForm) return;
        if (pickerModal && !pickerModal.hidden) closeModal(pickerModal);
        resetForm(voidForm);
        $('[data-rm-entry-id]', voidForm).value = entry.id;
        recap(voidForm, [
            ['Akun', entry.account],
            ['Nominal', entry.amount_text],
            ['Tanggal', entry.date_text],
            ['Jenis', entry.source_type],
        ]);
        openModal('void');
    });

    if (voidForm) {
        const reasonSel = $('[name=void_reason]', voidForm);
        if (reasonSel) reasonSel.addEventListener('change', () => {
            const wrap = $('[data-rm-other-wrap]', voidForm);
            if (wrap) wrap.hidden = reasonSel.value !== 'Lainnya';
        });
        voidForm.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const payload = Object.fromEntries(new FormData(voidForm).entries());
            busy(voidForm, true, 'Menghapus…');
            try {
                const res = await post(URLS.void(payload.entry_id), payload);
                toast(res.message || 'Data berhasil dihapus dari data aktif. Riwayat tetap tersimpan.');
                closeModal(voidModal);
                reloadPage();
            } catch (e) {
                showError(voidForm, e.message, e.field);
            } finally {
                busy(voidForm, false, 'Hapus Data');
            }
        });
    }

    /* ------------------------------------------------------------------ *
     * Manage drawer: project-level edit + per-transaction edit/hapus (§17, §18)
     * ------------------------------------------------------------------ */
    const manageModal = $('[data-rm-modal="manage"]');
    const txnModal = $('[data-rm-modal="txn-edit"]');
    const txnForm = txnModal ? $('[data-rm-form="txn-edit"]', txnModal) : null;
    let manageProject = null;

    async function openManage(projectId) {
        if (!manageModal) return;
        const body = $('[data-rm-manage-body]', manageModal);
        body.innerHTML = '<div class="rm-empty">Memuat data manual…</div>';
        openModal('manage');
        let data;
        try {
            data = await getJSON(URLS.entries, { project: projectId });
        } catch (e) {
            body.innerHTML = `<div class="rm-empty">${e.message}</div>`;
            return;
        }
        manageProject = data.project;
        // The transaction Edit button resolves its row from here (one fetch
        // feeds both the table and the form).
        window.__rmManageEntries = data.entries || [];
        $('[data-rm-manage-sub]', manageModal).textContent =
            manageProject ? `${manageProject.number} · ${manageProject.name || '(tanpa nama)'}` : '';
        body.innerHTML = '';
        body.appendChild(projectPanel(manageProject));
        body.appendChild(transactionPanel(data.entries || []));
    }

    function projectPanel(project) {
        const wrap = document.createElement('div');
        if (!project) return wrap;
        const editable = project.can_edit_master && !CFG.closed;
        wrap.className = 'rm-fieldset';
        wrap.innerHTML = `
            <legend>Project Level</legend>
            ${editable ? '' : `<div class="rm-readonly-note">
                <i class="bi bi-lock"></i> ${project.is_manual_source
                    ? 'Periode sudah ditutup: data master project tidak dapat diubah.'
                    : 'Project berasal dari data import — data master tidak dapat diubah langsung.'}
            </div>`}
            <form class="rm-form" data-rm-form="project" novalidate style="padding:0;">
                <div class="rm-form-error" data-rm-error hidden></div>
                <div class="rm-grid">
                    <label class="rm-field"><span class="rm-label">Nama Proyek / Objek</span>
                        <input type="text" name="project_name" class="rm-input" maxlength="300"
                               value="${escapeAttr(project.name)}" ${editable ? '' : 'disabled'}></label>
                    <label class="rm-field"><span class="rm-label">No Proyek</span>
                        <input type="text" name="project_number" class="rm-input" maxlength="60"
                               value="${escapeAttr(project.number)}" ${editable ? '' : 'disabled'}></label>
                    <label class="rm-field"><span class="rm-label">Nilai Proyek</span>
                        <input type="text" name="project_value" class="rm-input rm-money"
                               inputmode="decimal" value="${escapeAttr(project.value)}"
                               ${editable ? '' : 'disabled'}>
                        <span class="rm-hint">Nilai master, bukan hasil penjumlahan GL.</span></label>
                </div>
                ${editable ? `<div class="rm-foot-btns" style="margin-top:10px;">
                    <button type="submit" class="rm-btn rm-btn-primary" data-rm-submit>
                        <span class="rm-spinner" hidden></span><span data-rm-submit-text>Simpan Project</span>
                    </button></div>` : ''}
            </form>`;
        const form = $('[data-rm-form="project"]', wrap);
        if (editable && form) {
            form.dataset.projectId = project.id;
            form.addEventListener('submit', async (ev) => {
                ev.preventDefault();
                const payload = Object.fromEntries(new FormData(form).entries());
                busy(form, true, 'Menyimpan…');
                try {
                    const res = await post(URLS.projectEdit(project.id), payload);
                    toast(res.message || 'Perubahan berhasil disimpan.');
                    closeModal(manageModal);
                    reloadPage();
                } catch (e) {
                    showError(form, e.message, e.field);
                } finally {
                    busy(form, false, 'Simpan Project');
                }
            });
        }
        return wrap;
    }

    function transactionPanel(entries) {
        const wrap = document.createElement('div');
        wrap.className = 'rm-fieldset';
        wrap.style.marginTop = '14px';
        wrap.innerHTML = '<legend>Transaction Level</legend>';
        if (!entries.length) {
            const empty = document.createElement('div');
            empty.className = 'rm-empty';
            empty.textContent = 'Belum ada pengakuan manual aktif pada project ini.';
            wrap.appendChild(empty);
            return wrap;
        }
        const table = document.createElement('div');
        table.className = 'rm-table-wrap';
        table.innerHTML = `
            <table class="rm-table"><thead><tr>
                <th>Tanggal</th><th>No Bukti</th><th>No Dokumen</th><th>Keterangan</th>
                <th class="num">Nominal</th><th class="num">Action</th>
            </tr></thead><tbody></tbody></table>`;
        const tbody = $('tbody', table);
        entries.forEach((entry) => {
            const tr = document.createElement('tr');
            const actions = [];
            if (entry.can_edit && !CFG.closed) {
                actions.push(`<button type="button" class="rm-btn rm-btn-mini rm-btn-outline"
                    data-rm-edit-entry="${entry.id}">Edit</button>`);
            }
            if (entry.can_void && !CFG.closed) {
                actions.push(`<button type="button" class="rm-btn rm-btn-mini rm-btn-danger"
                    data-rm-void-entry="${entry.id}">Hapus</button>`);
            }
            if (entry.source_type !== 'MANUAL') {
                actions.unshift('<span class="rm-badge rm-badge-adj">ADJ</span>');
            }
            tr.innerHTML = `
                <td class="nowrap"></td><td></td><td></td><td></td>
                <td class="num tabular-nums"></td>
                <td class="num">${actions.join(' ') || '<span class="rm-muted">—</span>'}</td>`;
            const cells = tr.querySelectorAll('td');
            cells[0].textContent = entry.date_text;
            cells[1].textContent = entry.evidence_number || '-';
            cells[2].textContent = entry.document_number || '-';
            cells[3].textContent = entry.description || '-';
            cells[4].textContent = entry.amount_text;
            tbody.appendChild(tr);
        });
        wrap.appendChild(table);
        return wrap;
    }

    function escapeAttr(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
            .replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    document.addEventListener('click', (ev) => {
        const btn = ev.target.closest('[data-rm-edit-entry]');
        if (!btn || !txnForm) return;
        const entry = (window.__rmManageEntries || []).find(
            (e) => String(e.id) === btn.dataset.rmEditEntry);
        if (!entry) return;
        resetForm(txnForm);
        $('[data-rm-txn-id]', txnForm).value = entry.id;
        $('[name=transaction_date]', txnForm).value = entry.date || '';
        $('[name=amount]', txnForm).value = entry.amount || '';
        $('[name=evidence_number]', txnForm).value = entry.evidence_number || '';
        $('[name=document_number]', txnForm).value = entry.document_number || '';
        $('[name=description]', txnForm).value = entry.description || '';
        openModal('txn-edit');
    });

    if (txnForm) {
        txnForm.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            const payload = Object.fromEntries(new FormData(txnForm).entries());
            busy(txnForm, true, 'Menyimpan…');
            try {
                const res = await post(URLS.edit(payload.entry_id), payload);
                toast(res.message || 'Perubahan berhasil disimpan.');
                closeModal(txnModal);
                closeModal(manageModal);
                reloadPage();
            } catch (e) {
                showError(txnForm, e.message, e.field);
            } finally {
                busy(txnForm, false, 'Simpan');
            }
        });
    }

    /* ------------------------------------------------------------------ *
     * Audit history (§32)
     * ------------------------------------------------------------------ */
    async function openHistory(projectId) {
        const modal = openModal('history');
        const body = $('[data-rm-history-body]', modal);
        $('[data-rm-history-title]', modal).textContent = 'Riwayat Perubahan';
        $('[data-rm-history-sub]', modal).textContent = 'Jejak audit yang tidak dapat diubah.';
        body.innerHTML = '<div class="rm-empty">Memuat riwayat perubahan…</div>';
        try {
            const data = await getHTML(URLS.history, { project: projectId });
            body.innerHTML = data.html;
        } catch (e) {
            body.innerHTML = `<div class="rm-empty">${e.message}</div>`;
        }
    }

    /* ------------------------------------------------------------------ *
     * Deleted data + restore (§22, §23)
     * ------------------------------------------------------------------ */
    const deletedModal = $('[data-rm-modal="deleted"]');

    document.addEventListener('click', async (ev) => {
        const opener = ev.target.closest('[data-rm-open="deleted"]');
        if (!opener) return;
        const modal = openModal('deleted');
        const body = $('[data-rm-deleted-body]', modal);
        body.innerHTML = '<div class="rm-empty">Memuat data terhapus…</div>';
        try {
            const types = CFG.allowedTypes.join(',');
            const data = await getHTML(URLS.deleted, { types });
            body.innerHTML = data.html;
        } catch (e) {
            body.innerHTML = `<div class="rm-empty">${e.message}</div>`;
        }
    });

    document.addEventListener('click', async (ev) => {
        const btn = ev.target.closest('[data-rm-restore]');
        if (!btn) return;
        if (btn.disabled) return;
        const original = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="rm-spinner"></span>';
        try {
            const res = await post(URLS.restore(btn.dataset.rmRestore), {});
            toast(res.message || 'Data berhasil dipulihkan.');
            closeModal(deletedModal);
            reloadPage();
        } catch (e) {
            toast(e.message, 'error');
            btn.disabled = false;
            btn.innerHTML = original;
        }
    });

    function reloadPage() {
        // The displayed totals are DERIVED (§45): reload so every column,
        // grand total and KPI reflects the new canonical actual.
        window.location.reload();
    }
})();
