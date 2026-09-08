/* Revenue table filter bar: MULTI-SELECT dropdowns for every filter.
   Shared by Data Revenue / Data TF / Data NTF Research / Data NTF Project.

   Contract:
     - each Field wraps a .df-select trigger + .df-panel with checkboxes
       name="<dimension>[]" (plus a "Semua" master option)
     - submit = plain GET: checked values become ?dim[]=a&dim[]=b ; "Semua"
       checked means NO constraint for that dimension
     - cascading: selecting Organization filters the PP option list in-place;
       selecting Jenis (type) filters the Account option list in-place
     - clicked-outside closes panels; "Semua" master clears specifics and
       vice-versa; label renders "1 dipilih / N dipilih" compactly.

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

    // parent -> child cascade by option value prefix
    const CASCADE = [
        { parent: 'org', child: 'pp', parentEmpty: 'Semua' },
        { parent: 'jenis', child: 'account', parentEmpty: 'Semua' },
    ];

    const msByName = (n) => form.querySelector('[data-multiselect][data-ms-name="' + n + '"]');
    const labelEl = (ms) => ms.querySelector('[data-ms-label]');
    const allBox = (ms) => ms.querySelector('[data-ms-all] input');
    const optionBoxes = (ms) => [...ms.querySelectorAll('[data-ms-option] input')].filter(b => b !== allBox(ms));
    const valueOf = (cb) => (cb.checked ? cb.value : null);

    function refreshLabel(ms) {
        const name = ms.dataset.msName;
        const checked = optionBoxes(ms).filter(b => b.checked).map(b => b.value);
        const all = allBox(ms);
        if (checked.length === 0 || all.checked) {
            labelEl(ms).textContent = DIM_EMPTY[name];
            if (all && !all.checked) all.checked = true;
        } else {
            if (all) all.checked = false;
            labelEl(ms).textContent = checked.length === 1
                ? checked[0]
                : DIM_COUNT[name].replace('{n}', checked.length);
        }
        updateChips();
    }

    /* ---------- chips (declared early: refreshLabel -> updateChips) ---------- */
    const chipsBox = form.parentElement.querySelector('[data-ms-chips]');
    const chipsList = chipsBox ? chipsBox.querySelector('.df-chips-list') : null;
    const clearAllBtn = chipsBox ? chipsBox.querySelector('[data-ms-clear-all-chips]') : null;

    /* ---------- dropdown open/close + search ---------- */
    form.querySelectorAll('[data-multiselect]').forEach((ms) => {
        try {
        const trigger = ms.querySelector('[data-ms-trigger]');
        const panel = ms.querySelector('[data-ms-panel]');
        const search = ms.querySelector('[data-ms-search]');
        const name = ms.dataset.msName;

        const open = () => {
            panel.hidden = false;
            trigger.setAttribute('aria-expanded', 'true');
            if (search) { search.value = ''; filter(); search.focus(); }
        };
        const close = () => { panel.hidden = true; trigger.setAttribute('aria-expanded', 'false'); };
        const filter = () => {
            const needle = (search ? search.value : '').toLowerCase();
            ms.querySelectorAll('[data-ms-option]').forEach((opt) => {
                const txt = opt.textContent.trim().toLowerCase();
                opt.dataset.hidden = (needle && !txt.includes(needle)) ? '1' : '0';
            });
        };

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
            search.addEventListener('input', filter);
            search.addEventListener('keydown', (e) => e.stopPropagation());
        }
        ms.querySelector('[data-ms-select-all]')?.addEventListener('click', () => {
            optionBoxes(ms).forEach(b => { b.checked = true; });
            const a = allBox(ms); if (a) a.checked = false;
            refreshLabel(ms);
        });
        ms.querySelector('[data-ms-clear]')?.addEventListener('click', () => {
            optionBoxes(ms).forEach(b => { b.checked = false; });
            const a = allBox(ms); if (a) a.checked = true;
            refreshLabel(ms);
        });
        allBox(ms)?.addEventListener('change', () => {
            if (allBox(ms).checked) optionBoxes(ms).forEach(b => { b.checked = false; });
            refreshLabel(ms);
        });
        optionBoxes(ms).forEach((b) => {
            b.addEventListener('change', () => {
                const a = allBox(ms);
                if (b.checked && a) a.checked = false;
                refreshLabel(ms);
                cascade(name);
            });
        });

        // label should already reflect server-side selections
        refreshLabel(ms);
        } catch (e) { throw e; }
    });

    /* ---------- cascading: narrow child option list from parent selection ----------
       Child option carries data-ms-parent = the parent value it belongs to
       (PP option -> organization pk; Account option -> category code).
       When the parent has checked values, children whose data-ms-parent is
       not among them are hidden; clearing the parent shows all children. */
    function cascade(parentName) {
        const rule = CASCADE.find(r => r.parent === parentName);
        if (!rule) return;
        const parentMs = msByName(rule.parent);
        const childMs = msByName(rule.child);
        if (!parentMs || !childMs) return;
        const selected = optionBoxes(parentMs).filter(b => b.checked).map(b => b.value);
        childMs.querySelectorAll('[data-ms-option]').forEach((opt) => {
            if (opt.dataset.msAll !== undefined) return; // keep "Semua" always visible
            const needed = opt.dataset.msParent;
            opt.dataset.hidden = (selected.length && needed && !selected.includes(needed)) ? '1' : '0';
        });
    }


    function activeSurvey() {
        const out = {};
        Object.keys(DIM_EMPTY).forEach((n) => {
            const ms = msByName(n);
            if (!ms) return;
            const vals = optionBoxes(ms).filter(b => b.checked).map(b => b.value);
            out[n] = vals;
        });
        const q = (form.querySelector('input[name="q"]').value || '').trim();
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
            vals.forEach((val) => {
                add(label, val, () => {
                    const box = ms.querySelector('input[value="' + CSS.escape(val) + '"]');
                    if (box) box.checked = false;
                    const a = allBox(ms); if (a) a.checked = (optionBoxes(ms).filter(b => b.checked).length === 0);
                    refreshLabel(ms); cascade(k);
                });
            });
        });
        if (v.q) add('Pencarian', v.q, () => { form.querySelector('input[name="q"]').value = ''; updateChips(); });
    }
    if (clearAllBtn) clearAllBtn.addEventListener('click', () => {
        Object.keys(DIM_EMPTY).forEach((n) => {
            const ms = msByName(n); if (!ms) return;
            optionBoxes(ms).forEach(b => { b.checked = false; });
            const a = allBox(ms); if (a) a.checked = true;
            refreshLabel(ms);
        });
        form.querySelector('input[name="q"]').value = '';
        updateChips();
    });

    /* ---------- submit ---------- */
    // The form is a plain GET submit; checkboxes named x[] are serialized
    // automatically as multiple ?x[]= values. Django's QueryDict.getlist
    // reads both ?x= and ?x[]= (handled server-side in RevenueContext).

    /* ---------- init ---------- */
    updateChips();
    Object.keys(DIM_EMPTY).forEach((n) => cascade(n));
})();