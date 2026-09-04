/* NTF Project list: expandable row loads recognition history via AJAX and
   renders into the panel (visual consistent with the finance design). */
(function () {
    'use strict';
    const rows = document.querySelectorAll('.rev-row-expand');
    if (!rows.length) return;

    rows.forEach((row) => {
        row.addEventListener('click', () => {
            // NTF Project rows carry data-project; TF/NTF Research rows carry
            // data-url on the row itself (no project id) find sibling panel.
            let panel = null;
            if (row.dataset.project) {
                panel = document.querySelector(`.rev-detail-panel[data-project-panel="${row.dataset.project}"]`);
            } else {
                const next = row.nextElementSibling;
                if (next && next.classList && next.classList.contains('rev-detail-panel')) panel = next;
            }
            if (!panel) return;
            const open = panel.classList.toggle('open');
            row.classList.toggle('open', open);
            if (open) panel.hidden = false;
            if (open) loadPanel(row, panel);
        });
        row.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                row.click();
            }
        });
    });

    async function loadPanel(row, panel) {
        if (panel.dataset.loaded) return;
        panel.dataset.loaded = '1';
        const inner = document.createElement('div');
        inner.className = 'rev-detail-inner';
        panel.appendChild(inner);
        inner.innerHTML = '<div style="color:#64748B;font-size:13px;">Memuat riwayat pengakuan…</div>';
        try {
            const url = row.dataset.url;
            const res = await fetch(url, { method: 'GET', cache: 'no-store', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const ct = res.headers.get('Content-Type') || '';
            let html = await res.text();
            if (ct.includes('application/json')) {
                try { html = JSON.parse(html).html; } catch (e) { /* keep raw */ }
            }
            inner.innerHTML = html;
        } catch (err) {
            inner.innerHTML = '<div style="color:#DC2626;font-size:13px;">Gagal memuat riwayat pengakuan.</div>';
        }
    }
})();
