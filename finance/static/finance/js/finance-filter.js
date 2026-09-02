/* Financial Performance Overview filter card: GET submit (Terapkan), active
   chips for non-default Campus/Unit, and Reset back to the latest period.
   Backend parameter contract (year, month, campus, unit) is untouched —
   the form is a plain GET to finance:dashboard. */
(function () {
    'use strict';
    const form = document.getElementById('finance-filter-form');
    if (!form) return;

    const card = document.getElementById('finance-filter-card');
    const applyBtn = document.getElementById('finance-apply-btn');
    const resetBtn = document.getElementById('finance-reset-btn');
    const chipsBox = document.getElementById('finance-chips');
    const chipsList = document.getElementById('finance-chips-list');

    const selects = {
        year: document.getElementById('f-year'),
        month: document.getElementById('f-month'),
        campus: document.getElementById('f-campus'),
        unit: document.getElementById('f-unit'),
    };

    const LABELS = { year: 'Tahun', month: 'Bulan', campus: 'Campus', unit: 'Organisasi' };
    // A value equal to the form default is not an "active" filter.
    const DEFAULTS = {
        campus: 'all',
        unit: 'all',
        year: form.dataset.defaultYear,
        month: form.dataset.defaultMonth,
    };

    const MONTH_NAMES = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
        'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];

    function labelFor(key, value) {
        if (key === 'month') {
            const n = parseInt(value, 10);
            return (MONTH_NAMES[n - 1] || value);
        }
        return value;
    }

    function isActive(key, value) {
        return String(value) !== String(DEFAULTS[key]);
    }

    function activeKeys() {
        return Object.keys(selects).filter((k) => isActive(k, selects[k].value));
    }

    function updateChips() {
        const active = activeKeys();
        chipsList.innerHTML = '';
        if (active.length === 0) {
            chipsBox.hidden = true;
            resetBtn.disabled = true;
            return;
        }
        chipsBox.hidden = false;
        resetBtn.disabled = false;

        active.forEach((key) => {
            const value = selects[key].value;
            const chip = document.createElement('span');
            chip.className = 'df-chip';
            const txt = document.createElement('span');
            txt.textContent = LABELS[key] + ': ' + labelFor(key, value);
            const x = document.createElement('button');
            x.className = 'df-chip-x';
            x.setAttribute('aria-label', 'Hapus ' + LABELS[key]);
            x.textContent = '\u00d7';
            x.addEventListener('click', () => {
                selects[key].value = DEFAULTS[key];
                updateChips();
                form.submit();
            });
            chip.appendChild(txt);
            chip.appendChild(x);
            chipsList.appendChild(chip);
        });
    }

    resetBtn.addEventListener('click', () => {
        if (resetBtn.disabled) return;
        Object.keys(selects).forEach((k) => { selects[k].value = DEFAULTS[k]; });
        form.submit();
    });

    // Selecting values never auto-submits; Terapkan / chip-x / Reset do.
    updateChips();
})();
