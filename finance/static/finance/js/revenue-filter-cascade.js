/* Dependent (cascading) Revenue filters.
   Organization -> reloads PP options; Revenue Type -> reloads Account options.
   Keep selections valid: when the parent changes, a child value that is no
   longer in the option set is reset to 'all'. */
(function () {
    'use strict';
    const form = document.getElementById('revenue-filter-form');
    if (!form) return;

    const orgSel = document.getElementById('rv-org');
    const typeSel = document.getElementById('rv-type');
    const ppSel = document.getElementById('rv-pp');
    const accSel = document.getElementById('rv-account');

    async function loadOptions(url, into) {
        const res = await fetch(url, { method: 'GET', cache: 'no-store' });
        if (!res.ok) return [];
        const data = await res.json();
        into.innerHTML = '';
        const all = document.createElement('option');
        all.value = 'all';
        all.textContent = into.dataset.allLabel || 'Semua';
        into.appendChild(all);
        data.forEach((item) => {
            const opt = document.createElement('option');
            opt.value = item.value;
            opt.textContent = item.label;
            into.appendChild(opt);
        });
        return data;
    }

    if (orgSel && ppSel) {
        orgSel.addEventListener('change', () => {
            const val = orgSel.value;
            const url = '/dashboard/revenue/filter/pps/?org=' + encodeURIComponent(val);
            loadOptions(url, ppSel).then(() => {
                if (ppSel.value === 'all' && !ppSel.querySelector('option[value="all"]')) {
                    // keep valid
                }
            });
        });
    }
    if (typeSel && accSel) {
        typeSel.addEventListener('change', () => {
            const val = typeSel.value;
            const url = '/dashboard/revenue/filter/accounts/?type=' + encodeURIComponent(val);
            loadOptions(url, accSel);
        });
    }
})();
