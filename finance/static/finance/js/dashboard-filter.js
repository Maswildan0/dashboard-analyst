/* Financial filter toolbar behaviour: multi-select dropdowns, debounced
   search, active-filter chips, reset, export and loading states. */
(function () {
    'use strict';

    const form = document.getElementById('df-form');
    if (!form) return;

    const applyBtn = document.getElementById('df-apply-btn');
    const resetBtn = document.getElementById('df-reset-btn');
    const exportBtn = document.getElementById('df-export-btn');
    const exportMenu = document.getElementById('df-export-menu');
    const chipsBox = document.getElementById('df-chips');
    const chipsList = document.getElementById('df-chips-list');
    const clearAll = document.getElementById('df-clear-all');

    /* ---------------- Multi-select dropdowns ---------------- */
    function initDropdowns() {
        document.querySelectorAll('#filter-toolbar [data-multiselect]').forEach((ms) => {
            const trigger = ms.querySelector('[data-ms-trigger]');
            const panel = ms.querySelector('[data-ms-panel]');
            const search = ms.querySelector('[data-ms-search]');
            const list = ms.querySelector('[data-ms-list]');
            const labelEl = ms.querySelector('[data-ms-label]');
            const allBox = ms.querySelector('[data-ms-all] input');
            const opts = [...ms.querySelectorAll('[data-ms-option] input')].filter(b => b !== allBox);
            const name = ms.dataset.msName;

            const countText = (n) => {
                const map = {
                    tahun: n + ' tahun dipilih',
                    bulan: n + ' bulan dipilih',
                    direktorat: n + ' direktorat',
                    kode_pp: n + ' kode PP',
                    tipe: n + ' tipe',
                };
                return map[name] || (n + ' dipilih');
            };
            const emptyText = () => ({
                tahun: 'Semua tahun',
                bulan: 'Semua bulan',
                direktorat: 'Semua direktorat',
                kode_pp: 'Semua kode PP',
                tipe: 'Semua tipe',
            }[name] || 'Semua');

            const refreshLabel = () => {
                const checked = opts.filter(b => b.checked).length;
                if (checked === 0) {
                    labelEl.textContent = emptyText();
                    if (allBox) allBox.checked = true;
                } else {
                    labelEl.textContent = checked === 1
                        ? (opts.find(b => b.checked)?.value || countText(1))
                        : countText(checked);
                    if (allBox) allBox.checked = false;
                }
                updateChips();
            };

            const open = () => {
                panel.hidden = false;
                trigger.setAttribute('aria-expanded', 'true');
                if (search) { search.value = ''; search.focus(); filterOptions(''); }
            };
            const close = () => {
                panel.hidden = true;
                trigger.setAttribute('aria-expanded', 'false');
            };

            const filterOptions = (q) => {
                const needle = q.toLowerCase();
                ms.querySelectorAll('[data-ms-option]').forEach((opt) => {
                    const text = opt.textContent.trim().toLowerCase();
                    opt.dataset.hidden = (needle && !text.includes(needle)) ? '1' : '0';
                });
            };

            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                panel.hidden ? open() : close();
            });
            // Keyboard: Enter/Space toggles, Escape closes.
            trigger.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); panel.hidden ? open() : close(); }
                if (e.key === 'Escape') close();
            });
            document.addEventListener('click', (e) => {
                if (!ms.contains(e.target)) close();
            });
            if (search) {
                search.addEventListener('input', () => filterOptions(search.value));
                search.addEventListener('keydown', (e) => e.stopPropagation());
            }

            // "Pilih semua" / "Hapus pilihan" (years panel only)
            ms.querySelector('[data-ms-select-all]')?.addEventListener('click', () => {
                opts.forEach(b => { b.checked = true; });
                if (allBox) allBox.checked = false;
                refreshLabel();
            });
            ms.querySelector('[data-ms-clear]')?.addEventListener('click', () => {
                opts.forEach(b => { b.checked = false; });
                if (allBox) allBox.checked = true;
                refreshLabel();
            });

            allBox?.addEventListener('change', () => {
                if (allBox.checked) opts.forEach(b => { b.checked = false; });
                refreshLabel();
            });
            opts.forEach((b) => {
                b.addEventListener('change', () => {
                    if (b.checked && allBox) allBox.checked = false;
                    refreshLabel();
                });
            });

            refreshLabel();
        });
    }

    /* ---------------- Debounced search + Enter ---------------- */
    let searchTimer = null;
    const qInput = form.querySelector('input[name="q"]');
    if (qInput) {
        const run = () => {
            // Debounce live search: just updates chips/URL hint, no submit.
            updateChips();
        };
        qInput.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(run, 350);
        });
        qInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                submitFilter();
            }
        });
    }

    /* ---------------- Chips ---------------- */
    const CHIP_LABELS = { tahun: 'Tahun', bulan: 'Bulan', direktorat: 'Direktorat', kode_pp: 'Kode PP', tipe: 'Tipe' };

    function activeValues() {
        const vals = {};
        ['tahun', 'bulan', 'direktorat', 'kode_pp', 'tipe'].forEach((n) => {
            const boxes = [...form.querySelectorAll(`input[name="${n}[]"]`)];
            const checked = boxes.filter(b => b.checked && b.value !== 'Semua').map(b => b.value);
            vals[n] = checked;
        });
        const q = (form.querySelector('input[name="q"]').value || '').trim();
        vals.q = q;
        return vals;
    }

    function countActive() {
        const v = activeValues();
        let n = (v.q ? 1 : 0);
        ['tahun', 'bulan', 'direktorat', 'kode_pp', 'tipe'].forEach((k) => { n += v[k].length; });
        return n;
    }

    function updateChips() {
        const v = activeValues();
        chipsList.innerHTML = '';
        const total = countActive();
        if (total === 0) {
            chipsBox.hidden = true;
            resetBtn.disabled = true;
            clearAll.hidden = true;
            return;
        }
        chipsBox.hidden = false;
        resetBtn.disabled = false;
        clearAll.hidden = total < 2;

        const addChip = (label, value, removeFn) => {
            const chip = document.createElement('span');
            chip.className = 'df-chip';
            const text = document.createElement('span');
            text.textContent = label + (value !== undefined ? ': ' + value : '');
            const x = document.createElement('button');
            x.className = 'df-chip-x';
            x.setAttribute('aria-label', 'Hapus ' + label);
            x.textContent = '\u00d7';
            x.addEventListener('click', removeFn);
            chip.appendChild(text);
            chip.appendChild(x);
            chipsList.appendChild(chip);
        };

        if (v.q) addChip('Pencarian', v.q, () => { qInput.value = ''; updateChips(); });
        v.tahun.forEach((t) => addChip('Tahun', t, () => uncheck('tahun', [t])));
        v.bulan.forEach((b) => addChip('Bulan', b, () => uncheck('bulan', [b])));
        v.direktorat.forEach((d) => addChip('Direktorat', d, () => uncheck('direktorat', [d])));
        v.kode_pp.forEach((k) => addChip('Kode PP', k, () => uncheck('kode_pp', [k])));
        v.tipe.forEach((t) => addChip('Tipe', t, () => uncheck('tipe', [t])));

        function uncheck(name, values) {
            const boxes = [...form.querySelectorAll(`input[name="${name}[]"]`)];
            boxes.forEach((b) => { if (values.includes(b.value)) b.checked = false; });
            // re-check the "Semua" master if nothing else is checked
            const anyLeft = boxes.some(b => b.checked && b.value !== 'Semua');
            boxes.forEach((b) => { if (b.value === 'Semua') b.checked = !anyLeft; });
            updateChips();
        }
        function uncheckAll(name) {
            const boxes = [...form.querySelectorAll(`input[name="${name}[]"]`)];
            boxes.forEach((b) => { b.checked = b.value === 'Semua'; });
            updateChips();
        }
    }

    /* ---------------- Apply / submit with loading ---------------- */
    function submitFilter() {
        if (applyBtn.classList.contains('is-loading')) return;
        applyBtn.classList.add('is-loading');
        // Prevent double submit.
        form.submit();
    }

    applyBtn.addEventListener('click', (e) => {
        e.preventDefault();
        // Sync "Semua" masters: checking the master clears specifics (except tahun Semua kept).
        form.querySelectorAll('[data-ms-all] input').forEach((b) => {
            if (b.checked && b.name !== 'tahun[]') {
                const ms = b.closest('[data-multiselect]');
                ms.querySelectorAll('[data-ms-option] input').forEach((o) => { if (o !== b) o.checked = false; });
            }
        });
        // Picking a specific month clears quarter drill-through.
        const bulanMS = [...document.querySelectorAll('[data-multiselect]')].find(m => m.dataset.msName === 'bulan');
        if (bulanMS && bulanMS.querySelectorAll('input:checked:not([value="Semua"])').length > 0) {
            form.querySelector('input[name="triwulan"]')?.remove();
        }
        submitFilter();
    });

    resetBtn.addEventListener('click', () => {
        if (resetBtn.disabled) return;
        // Clear all filters -> navigate with only per_page (backend defaults).
        const url = new URL(form.action, location.href);
        url.search = '';
        url.searchParams.set('per_page', form.querySelector('input[name="per_page"]')?.value || '20');
        window.location.href = url.toString();
    });

    clearAll.addEventListener('click', () => {
        ['tahun', 'bulan', 'direktorat', 'kode_pp', 'tipe'].forEach((n) => {
            const boxes = [...form.querySelectorAll(`input[name="${n}[]"]`)];
            boxes.forEach((b) => { b.checked = b.value === 'Semua'; });
        });
        qInput.value = '';
        updateChips();
    });

    /* ---------------- Export ---------------- */
    exportBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        exportMenu.hidden = !exportMenu.hidden;
    });
    document.addEventListener('click', () => { exportMenu.hidden = true; });

    exportMenu.querySelectorAll('.df-export-item').forEach((item) => {
        item.addEventListener('click', () => {
            const fmt = item.dataset.export;
            if (!fmt) return;
            if (item.classList.contains('is-loading')) return;
            // Only CSV is supported by the backend (realisasi-export).
            const btn = item;
            btn.classList.add('is-loading');
            btn.textContent = 'Menyiapkan...';
            // Build export URL with ALL active filters.
            const url = new URL(form.action.replace('/table', '/export'), location.href);
            const params = new URLSearchParams();
            const q = qInput.value.trim();
            if (q) params.set('q', q);
            ['tahun', 'bulan', 'direktorat', 'kode_pp', 'tipe'].forEach((n) => {
                const checked = [...form.querySelectorAll(`input[name="${n}[]"]:checked`)].map(b => b.value);
                // Exclude "Semua" except tahun Semua which is meaningful? For export, Semua = no filter.
                checked.filter(v => v !== 'Semua').forEach((v) => params.append(n + '[]', v));
            });
            window.location.href = url.origin + url.pathname + '?' + params.toString();
            setTimeout(() => { btn.classList.remove('is-loading'); btn.textContent = 'Export CSV'; }, 1500);
        });
    });

    /* ---------------- Init ---------------- */
    initDropdowns();
    updateChips();
})();
