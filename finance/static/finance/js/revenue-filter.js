/* Revenue Overview filter card: single-select filters + Terapkan + chips.
   Reuses window.__refreshDashboard (exposed by the dashboard bundle) so
   charts refresh with the exact same payload pipeline. */
(function () {
    'use strict';
    const card = document.getElementById('revenue-filter-card');
    if (!card) return;

    const selects = [...card.querySelectorAll('select[data-filter]')];
    const applyBtn = document.getElementById('revenue-apply-btn');
    const resetBtn = document.getElementById('revenue-reset-btn');
    const chipsBox = document.getElementById('revenue-chips');
    const chipsList = document.getElementById('revenue-chips-list');

    const LABELS = { tipe: 'Tipe', direktorat: 'Direktorat', kode_pp: 'Kode PP', tahun: 'Tahun' };
    const DEFAULTS = { tipe: 'Semua', direktorat: 'Semua', kode_pp: 'Semua', tahun: 'Semua' };

    function currentValues() {
        const v = {};
        selects.forEach((sel) => { v[sel.dataset.filter] = sel.value; });
        return v;
    }

    function countActive() {
        const v = currentValues();
        return selects.filter((sel) => v[sel.dataset.filter] !== DEFAULTS[sel.dataset.filter]).length;
    }

    function updateChips() {
        const v = currentValues();
        chipsList.innerHTML = '';
        const active = selects.filter((sel) => v[sel.dataset.filter] !== DEFAULTS[sel.dataset.filter]);
        if (active.length === 0) {
            chipsBox.hidden = true;
            resetBtn.disabled = true;
            return;
        }
        chipsBox.hidden = false;
        resetBtn.disabled = false;

        active.forEach((sel) => {
            const key = sel.dataset.filter;
            const chip = document.createElement('span');
            chip.className = 'df-chip';
            const txt = document.createElement('span');
            txt.textContent = LABELS[key] + ': ' + v[key];
            const x = document.createElement('button');
            x.className = 'df-chip-x';
            x.setAttribute('aria-label', 'Hapus ' + LABELS[key]);
            x.textContent = '\u00d7';
            x.addEventListener('click', () => {
                sel.value = DEFAULTS[key];
                updateChips();
                apply();
            });
            chip.appendChild(txt);
            chip.appendChild(x);
            chipsList.appendChild(chip);
        });
    }

    async function apply() {
        if (applyBtn.classList.contains('is-loading')) return;
        applyBtn.classList.add('is-loading');
        try {
            if (window.__refreshDashboard) {
                await window.__refreshDashboard();
            } else {
                // Fallback: dispatch change (bundle listener removed, so just reload charts via fetch)
                const ev = new Event('change', { bubbles: true });
                selects.forEach((sel) => sel.dispatchEvent(ev));
            }
        } finally {
            setTimeout(() => applyBtn.classList.remove('is-loading'), 400);
        }
        updateChips();
    }

    applyBtn.addEventListener('click', apply);

    resetBtn.addEventListener('click', () => {
        if (resetBtn.disabled) return;
        selects.forEach((sel) => { sel.value = DEFAULTS[sel.dataset.filter]; });
        updateChips();
        apply();
    });

    // Selecting a value does not auto-apply; only Terapkan / chip-x / Reset do.
    updateChips();
})();
