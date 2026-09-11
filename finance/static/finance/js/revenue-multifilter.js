/* Revenue table filter bar: MULTI-SELECT dropdowns for every filter.
   Shared by Data Revenue / Data TF / Data NTF Research / Data NTF Project.

   Contract:
     - each Field wraps a .df-select trigger + .df-panel with checkboxes
       name="<dimension>[]" (plus a "Semua" master option)
     - submit = plain GET: checked values become ?dim[]=a&dim[]=b ; "Semua"
       checked means NO constraint for that dimension
     - cascading: selecting Organizations narrows the Kode PP option list;
       selecting Jenis Revenue narrows the Akun option list. Multi-parent
       selections show the union of their children.
     - clicked-outside closes panels; "Pilih semua"/"Bersihkan" act on the
       visible (cascaded) options; the trigger label renders the selection
       compactly ("1 dipilih" / "N dipilih").
     - chip summary uses the human label of each selected option.

   No framework — vanilla JS, works on all four revenue table pages.
*/
(function () {
    'use strict';
    const form = document.getElementById('revenue-filter-form');
    if (!form) return;

    const DIM_EMPTY = {
        jenis: 'Semua Revenue',
        tahun: 'Semua tahun',
        bulan: 'Semua bulan',
        org: 'Semua Organization',
        pp: 'Semua PP',
        account: 'Semua Akun',
    };
    const DIM_LABEL = {
        jenis: 'Jenis',
        tahun: 'Tahun',
        bulan: 'Bulan',
        org: 'Organization',
        pp: 'Kode PP',
        account: 'Akun',
    };
    const DIM_COUNT = {
        jenis: '{n} jenis',
        tahun: '{n} tahun',
        bulan: '{n} bulan',
        org: '{n} organization',
        pp: '{n} PP',
        account: '{n} akun',
    };

    // parent -> child cascade (child option carries data-ms-parent)
    const CASCADE = [
        { parent: 'org', child: 'pp' },
        { parent: 'jenis', child: 'account' },
    ];

    const msByName = (n) => form.querySelector('[data-multiselect][data-ms-name="' + n + '"]');
    const labelEl = (ms) => ms.querySelector('[data-ms-label]');
    const allBox = (ms) => ms.querySelector('[data-ms-all] input');
    const optionBoxes = (ms) => [...ms.querySelectorAll('[data-ms-option] input')].filter(b => b !== allBox(ms));
    const optionText = (input) => {
        const opt = input.closest('[data-ms-option]');
        const txt = opt && opt.querySelector('.df-option-text');
        return txt ? txt.textContent.trim() : input.value;
    };

    /* ---------- chips (chipsBox declared early: refreshLabel -> updateChips) ---------- */
    const chipsBox = form.parentElement.querySelector('[data-ms-chips]');
    const chipsList = chipsBox ? chipsBox.querySelector('.df-chips-list') : null;
    const clearAllBtn = chipsBox ? chipsBox.querySelector('[data-ms-clear-all-chips]') : null;

    function refreshLabel(ms) {
        const name = ms.dataset.msName;
        const checked = optionBoxes(ms).filter(b => b.checked);
        const all = allBox(ms);
        if (checked.length === 0 || all.checked) {
            labelEl(ms).textContent = DIM_EMPTY[name];
            if (all && !all.checked) all.checked = true;
        } else {
            if (all) all.checked = false;
            labelEl(ms).textContent = checked.length === 1
                ? optionText(checked[0])
                : DIM_COUNT[name].replace('{n}', checked.length);
        }
        updateChips();
    }

    /* ---------- visibility: search text AND parent cascade ---------- */
    function isCascadeVisible(opt, parentSelected) {
        if (!parentSelected.length) return true;
        const needed = opt.dataset.msParent;
        return !needed || parentSelected.includes(needed);
    }

    function parentSelectedValues(ms) {
        const rule = CASCADE.find(r => r.child === ms.dataset.msName);
        if (!rule) return [];
        const parentMs = msByName(rule.parent);
        if (!parentMs) return [];
        return optionBoxes(parentMs).filter(b => b.checked).map(b => b.value);
    }

    function applyVisibility(ms) {
        const search = ms.querySelector('[data-ms-search]');
        const needle = (search ? search.value : '').trim().toLowerCase();
        const parentSelected = parentSelectedValues(ms);
        ms.querySelectorAll('[data-ms-option]').forEach((opt) => {
            if (opt.hasAttribute('data-ms-all')) { opt.dataset.hidden = '0'; return; }
            const matchesSearch = !needle || opt.textContent.trim().toLowerCase().includes(needle);
            opt.dataset.hidden = matchesSearch && isCascadeVisible(opt, parentSelected) ? '0' : '1';
        });
    }

    /* Cascade a parent change: hide non-matching children AND deselect any
       child that the new parent selection no longer covers, so the submitted
       query never carries stale PP/account values. */
    function cascade(parentName) {
        const rule = CASCADE.find(r => r.parent === parentName);
        if (!rule) return;
        const childMs = msByName(rule.child);
        if (!childMs) return;
        const parentMs = msByName(rule.parent);
        const parentSelected = parentMs
            ? optionBoxes(parentMs).filter(b => b.checked).map(b => b.value)
            : [];
        if (parentSelected.length) {
            optionBoxes(childMs).forEach((b) => {
                const opt = b.closest('[data-ms-option]');
                const needed = opt && opt.dataset.msParent;
                if (b.checked && needed && !parentSelected.includes(needed)) b.checked = false;
            });
        }
        applyVisibility(childMs);
        refreshLabel(childMs);
    }

    /* ---------- dropdown open/close + search ---------- */
    form.querySelectorAll('[data-multiselect]').forEach((ms) => {
        const trigger = ms.querySelector('[data-ms-trigger]');
        const panel = ms.querySelector('[data-ms-panel]');
        const search = ms.querySelector('[data-ms-search]');
        const name = ms.dataset.msName;

        const open = () => {
            panel.hidden = false;
            trigger.setAttribute('aria-expanded', 'true');
            if (search) { search.value = ''; applyVisibility(ms); search.focus(); }
            else { applyVisibility(ms); }
        };
        const close = () => { panel.hidden = true; trigger.setAttribute('aria-expanded', 'false'); };

        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            panel.hidden ? open() : close();
        });
        trigger.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); panel.hidden ? open() : close(); }
            if (e.key === 'Escape') close();
        });
        document.addEventListener('click', (e) => {
            if (!ms.contains(e.target)) close();
        });
        if (search) {
            search.addEventListener('input', () => applyVisibility(ms));
            search.addEventListener('keydown', (e) => e.stopPropagation());
        }
        ms.querySelector('[data-ms-select-all]')?.addEventListener('click', () => {
            optionBoxes(ms).forEach((b) => {
                const opt = b.closest('[data-ms-option]');
                if (opt && opt.dataset.hidden === '1') return; // only visible options
                b.checked = true;
            });
            const a = allBox(ms); if (a) a.checked = false;
            refreshLabel(ms);
            cascade(name);
        });
        ms.querySelector('[data-ms-clear]')?.addEventListener('click', () => {
            optionBoxes(ms).forEach(b => { b.checked = false; });
            const a = allBox(ms); if (a) a.checked = true;
            refreshLabel(ms);
            cascade(name);
        });
        allBox(ms)?.addEventListener('change', () => {
            if (allBox(ms).checked) optionBoxes(ms).forEach(b => { b.checked = false; });
            refreshLabel(ms);
            cascade(name);
        });
        optionBoxes(ms).forEach((b) => {
            b.addEventListener('change', () => {
                const a = allBox(ms);
                if (b.checked && a) a.checked = false;
                refreshLabel(ms);
                cascade(name);
            });
        });

        // label + visibility should reflect the server-side selections on load
        applyVisibility(ms);
        refreshLabel(ms);
    });

    /* ---------- active filter chips ---------- */
    function activeSurvey() {
        const out = {};
        Object.keys(DIM_EMPTY).forEach((n) => {
            const ms = msByName(n);
            if (!ms) return;
            out[n] = optionBoxes(ms).filter(b => b.checked).map(b => ({ value: b.value, label: optionText(b) }));
        });
        const qEl = form.querySelector('input[name="q"]');
        const q = qEl ? (qEl.value || '').trim() : '';
        if (q) out.q = q;
        return out;
    }

    function updateChips() {
        if (!chipsBox || !chipsList) return;
        const v = activeSurvey();
        chipsList.innerHTML = '';
        const keys = Object.keys(v).filter(k => k !== 'q');
        const total = keys.length + (v.q ? 1 : 0);
        if (total === 0) { chipsBox.hidden = true; if (clearAllBtn) clearAllBtn.hidden = true; return; }
        chipsBox.hidden = false;
        if (clearAllBtn) clearAllBtn.hidden = total < 2;
        const add = (label, val, onX) => {
            const chip = document.createElement('span');
            chip.className = 'df-chip';
            const t = document.createElement('span'); t.textContent = label + (val !== undefined ? ': ' + val : '');
            const x = document.createElement('button'); x.className = 'df-chip-x'; x.setAttribute('aria-label', 'Hapus ' + label); x.textContent = '\u00d7';
            x.addEventListener('click', onX);
            chip.appendChild(t); chip.appendChild(x); chipsList.appendChild(chip);
        };
        keys.forEach((k) => {
            const ms = msByName(k);
            const vals = v[k];
            if (!vals.length) return;
            const label = DIM_LABEL[k] || k;
            vals.forEach((item) => {
                add(label, item.label, () => {
                    const box = ms.querySelector('input[value="' + CSS.escape(item.value) + '"]');
                    if (box) box.checked = false;
                    const a = allBox(ms); if (a) a.checked = (optionBoxes(ms).filter(b => b.checked).length === 0);
                    refreshLabel(ms); cascade(k);
                });
            });
        });
        if (v.q) add('Pencarian', v.q, () => {
            const qEl = form.querySelector('input[name="q"]');
            if (qEl) qEl.value = '';
            updateChips();
        });
    }

    if (clearAllBtn) clearAllBtn.addEventListener('click', () => {
        Object.keys(DIM_EMPTY).forEach((n) => {
            const ms = msByName(n); if (!ms) return;
            optionBoxes(ms).forEach(b => { b.checked = false; });
            const a = allBox(ms); if (a) a.checked = true;
            refreshLabel(ms);
        });
        const qEl = form.querySelector('input[name="q"]');
        if (qEl) qEl.value = '';
        Object.keys(DIM_EMPTY).forEach((n) => cascade(n));
        updateChips();
    });

    /* ---------- submit ---------- */
    // Plain GET submit: checkboxes named x[] serialize to repeated ?x[]=
    // values; Django's QueryDict.getlist reads them all (RevenueContext).

    /* ---------- init ---------- */
    updateChips();
})();
