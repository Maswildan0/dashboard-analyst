// Hover pop animations for dashboard charts.
// Wraps each chart canvas in a positioned container, adds a floating value
// label on hover, and applies the .chart-popped scale/glow class.
(function () {
    'use strict';
    if (document.body.classList.contains('hover-animations-loaded')) return;
    document.body.classList.add('hover-animations-loaded');

    const CHART_IDS = ['chartA', 'chartB', 'chartD', 'chartE'];
    const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agt', 'Sep', 'Okt', 'Nov', 'Des'];

    // ------------------------------------------------------------------
    // Floating value label (single shared element, moved with the cursor).
    // ------------------------------------------------------------------
    const label = document.createElement('div');
    label.className = 'chart-value-label';
    document.body.appendChild(label);

    const LABEL_HIDE_DELAY = 120; // ms after leaving a bar/point
    let labelTimer = null;

    function showLabel(html, x, y) {
        clearTimeout(labelTimer);
        label.innerHTML = html;
        label.classList.add('label-visible');
        positionLabel(x, y);
    }

    function positionLabel(x, y) {
        const pad = 14;
        const rect = label.getBoundingClientRect();
        let left = x;
        let top = y - rect.height - 16;
        // Keep inside the viewport.
        if (left + rect.width / 2 > window.innerWidth - pad) {
            left = window.innerWidth - pad - rect.width / 2;
        }
        if (left - rect.width / 2 < pad) {
            left = pad + rect.width / 2;
        }
        if (top < pad) top = y + 24;
        label.style.left = left + 'px';
        label.style.top = top + 'px';
    }

    function hideLabelSoon() {
        clearTimeout(labelTimer);
        labelTimer = setTimeout(() => label.classList.remove('label-visible'), LABEL_HIDE_DELAY);
    }

    // ------------------------------------------------------------------
    // Per-chart wiring.
    // ------------------------------------------------------------------
    function wrapCanvas(canvas) {
        if (!canvas || canvas.parentElement.classList.contains('chart-hover-wrap')) return;
        const parent = canvas.parentElement;
        const wrap = document.createElement('div');
        wrap.className = 'chart-hover-wrap';
        wrap.style.cssText = 'position:relative;z-index:1;height:' + parent.style.height + ';';
        parent.insertBefore(wrap, canvas);
        wrap.appendChild(canvas);
        return wrap;
    }

    function fmtRp(v) {
        // Values are in Juta (Jt) for chart series; show full Rupiah like the
        // existing tooltips (v * 1_000_000).
        try {
            return 'Rp ' + Math.round(v * 1000000).toLocaleString('id-ID');
        } catch (e) {
            return 'Rp ' + v;
        }
    }

    function datasetLabel(chartKey, datasetIndex) {
        // Match the labels used by app.js for each chart.
        if (chartKey === 'chartA') {
            return datasetIndex === 0 ? 'RKA' : 'Realisasi';
        }
        if (chartKey === 'chartD') {
            const map = ['Tahun Ini', 'Tahun Sebelum', 'Capaian'];
            return map[datasetIndex] || 'Series';
        }
        if (chartKey === 'chartE') {
            const map = ['Tahun Sebelum', 'Tahun Ini', 'Capaian'];
            return map[datasetIndex] || 'Series';
        }
        return 'Series';
    }

    function onMove(e, canvas, chartKey) {
        // For line charts (D, E) also snap to the nearest point via index math
        // is complex without Chart.js; simplest reliable approach: use the
        // pixel position to pick the month from the canvas width.
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const idx = Math.max(0, Math.min(11, Math.floor((x / rect.width) * 12)));
        const month = MONTHS_SHORT[idx] || '';

        const payload = window.__DASHBOARD__;
        if (!payload) {
            showLabel('<span class="lbl-title">' + (month || 'Grafik') + '</span><span class="lbl-value">' + chartKey + '</span>', e.clientX, e.clientY);
            return;
        }

        let html = '<span class="lbl-title">' + (month ? month : chartKey) + '</span>';
        if (chartKey === 'chartA' && payload.chartA) {
            html += '<span class="lbl-value">RKA: ' + fmtRp(payload.chartA.rka[idx]) + '</span>';
            html += '<span class="lbl-value">Realisasi: ' + fmtRp(payload.chartA.realisasi[idx]) + '</span>';
        } else if (chartKey === 'chartD' && payload.chartD) {
            html += '<span class="lbl-value">Tahun Ini: ' + fmtRp(payload.chartD.tahunSekarang[idx]) + '</span>';
            html += '<span class="lbl-value">Tahun Sebelum: ' + fmtRp(payload.chartD.tahunLalu[idx]) + '</span>';
            html += '<span class="lbl-value">Capaian: ' + payload.chartD.capaian[idx] + '%</span>';
        } else if (chartKey === 'chartE' && payload.chartD) {
            html += '<span class="lbl-value">Tahun Ini: ' + fmtRp(payload.chartD.tahunSekarang[idx]) + '</span>';
            html += '<span class="lbl-value">Tahun Sebelum: ' + fmtRp(payload.chartD.tahunLalu[idx]) + '</span>';
            html += '<span class="lbl-value">Capaian: ' + payload.chartD.capaian[idx] + '%</span>';
        }
        showLabel(html, e.clientX, e.clientY);
    }

    function wireChart(canvas, chartKey) {
        const wrap = wrapCanvas(canvas);
        if (!wrap) return;

        canvas.addEventListener('mouseenter', () => {
            wrap.classList.add('chart-popped');
            canvas.style.cursor = 'pointer';
        });
        canvas.addEventListener('mouseleave', () => {
            wrap.classList.remove('chart-popped');
            hideLabelSoon();
        });
        canvas.addEventListener('mousemove', (e) => onMove(e, canvas, chartKey));
        canvas.addEventListener('mouseout', hideLabelSoon);
    }

    function init() {
        CHART_IDS.forEach((id) => {
            const canvas = document.getElementById(id);
            if (canvas) wireChart(canvas, id);
        });
        // Chart B pie canvas (created later by renderChartBPie) — re-scan
        // after a short delay and on mutation.
        const rescan = () => {
            const pie = document.getElementById('chartBPie');
            if (pie && !pie.__wired) {
                pie.__wired = true;
                wireChart(pie, 'chartB');
            }
        };
        setTimeout(rescan, 400);
        const obs = new MutationObserver(rescan);
        obs.observe(document.body, { childList: true, subtree: true });
        setTimeout(() => obs.disconnect(), 6000); // pie only appears on filter change later
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
