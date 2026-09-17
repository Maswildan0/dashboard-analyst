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

    /* ---------- card deep links (card = slicer) ----------
       Cards are real <a> elements, so they work without JS. Applying a filter
       here is in-place (no reload), which would leave those hrefs stale; the
       query is rebuilt through the shared builder owned by app.js
       (window.revenueFilterQuery — the same one the chart drill-down uses, fed
       by the same server-validated option contract). Only the query string is
       replaced: each card keeps the destination path the server rendered.

       The period month belongs to card links only (a chart click passes the
       month that was clicked instead), so it is supplied here as an override.
       Without the bundle (no server data) the server hrefs simply stand. */
    function rebuildCardLinks() {
        if (typeof window.revenueFilterQuery !== 'function') return;
        const periodMonth = card.dataset.periodMonth || '';
        const query = window.revenueFilterQuery(
            periodMonth ? { month: periodMonth } : {}).toString();
        document.querySelectorAll('a[data-revenue-link]').forEach((link) => {
            link.setAttribute('href', query ? link.pathname + '?' + query : link.pathname);
        });
    }

    /* Keep the page URL in step with the APPLIED filters: the overview filters
       live in selects and are not in the URL otherwise, so a fresh render after
       browser Back (Data Revenue -> Revenue Overview) would lose them.
       replaceState keeps this out of the history stack. */
    function syncUrl() {
        const params = new URLSearchParams();
        selects.forEach((sel) => { params.set(sel.dataset.filter, sel.value); });
        history.replaceState(history.state, '',
            location.pathname + (params.toString() ? '?' + params.toString() : ''));
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

    // One in-flight render at a time: repeated clicks must not start a second
    // refresh whose render could race the first one's chart lifecycle. The
    // guard complements (never replaces) the destroy-before-create contract in
    // the bundle.
    let rendering = false;

    async function apply() {
        if (rendering) return;
        rendering = true;
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
            rendering = false;
            applyBtn.classList.remove('is-loading');
        }
        updateChips();
        rebuildCardLinks();
        syncUrl();
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
    // The cards summarise what is currently displayed, so their links always
    // mirror the applied filters (server-rendered hrefs = no-JS baseline).
    // The URL carries the same filters so Back from a destination restores them.
    rebuildCardLinks();
    syncUrl();
})();
