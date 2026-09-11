import Chart from 'chart.js/auto';
import ChartDataLabels from 'chartjs-plugin-datalabels';

// Figma design tokens
const GRAY = '#5F5F60';
const RED = '#EB3237';
const GREEN = '#10B981';
const SLATE = '#94A3B8';
const GRID = '#E2E8F0';
const TICK = { color: '#94A3B8', font: { size: 11, weight: 600 } };

const baseOptions = (max, unit) => ({
    responsive: true,
    maintainAspectRatio: false,
    devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
    resizeDelay: 100,
    plugins: {
        legend: { display: false },
        // No value labels on the bar chart (ChartDataLabels is registered
        // globally for the pie leader lines; keep bars clean).
        datalabels: { display: false },
        tooltip: {
            callbacks: {
                label: (ctx) => {
                    const v = ctx.parsed.y;
                    if (unit === 'Jt') return `${ctx.dataset.label}: Rp ${(v * 1_000_000).toLocaleString('id-ID')}`;
                    return `${ctx.dataset.label}: ${v}${unit}`;
                },
                footer: SLICER_HINT_FOOTER,
            },
            ...SLICER_HINT_STYLE,
        },
    },
    scales: {
        x: { grid: { display: false }, ticks: { ...TICK } },
        y: {
            grid: { color: GRID },
            min: 0,
            max,
            ticks: { ...TICK, stepSize: max / 5, callback: (v) => v + unit },
        },
    },
});

const barDataset = (data, color, label) => ({
    label,
    data,
    backgroundColor: color,
    borderRadius: 3,
    borderSkipped: false,
    barPercentage: 0.82,
    categoryPercentage: 0.6,
    hoverBackgroundColor: color,
});

// ---------------------------------------------------------------------------
// Bar pop animation: the hovered bar scales up (transform origin at its base)
// and casts a soft glow. Implemented as a beforeDatasetsDraw overlay pass so
// it works without touching Chart.js internals.
// ---------------------------------------------------------------------------
const barPopPlugin = {
    id: 'barPop',
    afterDatasetsDraw(chart, _args, opts) {
        if (opts && opts.enabled === false) return;
        // Only bar charts pop; line charts keep their points/curves.
        if (chart.config.type !== 'bar') return;
        const active = chart.getActiveElements();
        if (!active.length) return;
        const { ctx } = chart;
        const meta = chart.getDatasetMeta(active[0].datasetIndex);
        const el = meta.data[active[0].index];
        if (!el || el.hidden) return;
        const area = chart.chartArea;
        const base = area.bottom;

        // Glow behind the hovered bar.
        ctx.save();
        ctx.shadowColor = 'rgba(235, 50, 55, 0.45)';
        ctx.shadowBlur = 18;
        ctx.shadowOffsetY = 4;
        const x = el.x, w = el.width;
        const y = el.y, h = base - el.y;
        ctx.fillStyle = el.options && el.options.backgroundColor ? el.options.backgroundColor : '#EB3237';
        // Scale up ~14% from the base center.
        const cx = x, newW = w * 1.18, newH = h * 1.10, newY = base - newH;
        ctx.beginPath();
        if (typeof ctx.roundRect === 'function') {
            ctx.roundRect(cx - newW / 2, newY, newW, newH, 4);
        } else {
            ctx.rect(cx - newW / 2, newY, newW, newH);
        }
        ctx.fill();
        ctx.restore();
    },
};

Chart.register(barPopPlugin);
Chart.register(ChartDataLabels);

// Chart labels -> month NUMBER. The revenue tables filter by number, never by
// month name, so every slicer resolves the clicked month here. Accepts the
// chart's short labels ('Agt', 'Okt') and full names, and falls back to the
// clicked data-point index when a label is unexpected.
const MONTH_NUMBERS = {
    jan: 1, feb: 2, mar: 3, apr: 4, mei: 5, jun: 6,
    jul: 7, agt: 8, agu: 8, aug: 8, sep: 9, okt: 10, oct: 10, nov: 11, des: 12, dec: 12,
};

function monthNumber(label, index) {
    const key = String(label === null || label === undefined ? '' : label).trim().toLowerCase().slice(0, 3);
    if (MONTH_NUMBERS[key]) return MONTH_NUMBERS[key];
    const i = Number(index);
    return Number.isInteger(i) && i >= 0 && i <= 11 ? i + 1 : null;
}

// Slicer affordance: every clickable chart says so in its tooltip. Only adds a
// footer; the existing value callbacks are untouched. The callback belongs in
// `callbacks`, the styling on the tooltip itself.
const SLICER_HINT_FOOTER = () => 'Klik untuk lihat Data Revenue';
const SLICER_HINT_STYLE = {
    footerColor: '#CBD5E1',
    footerFont: { size: 10, weight: 'normal' },
};

const charts = {};

const chartState = {
    payload: null,          // last payload applied to the charts
    controller: null,       // AbortController of the refresh currently in flight
};

function numArr(v) {
    return Array.isArray(v) ? v.filter(function (n) { return typeof n === 'number' && Number.isFinite(n); }) : [];
}

function dataHasContent(payload) {
    if (!payload || typeof payload !== 'object') return false;
    var a = numArr(payload.chartA && payload.chartA.rka).concat(
        numArr(payload.chartA && payload.chartA.realisasi),
        numArr(payload.chartD && payload.chartD.tahunSekarang),
        numArr(payload.chartD && payload.chartD.tahunLalu),
        numArr(payload.chartD && payload.chartD.capaian)
    );
    if (a.length) return true;
    var b = payload.chartB;
    if (b) {
        var values = b.type === 'pie'
            ? numArr((b.pie || []).map(function (s) { return s && s.value; }))
            : numArr((b.items || []).map(function (s) { return s && s.realisasi; }));
        if (values.length) return true;
    }
    return false;
}

function isValidPayload(payload) {
    return dataHasContent(payload);
}

function validData(v) {
    return Array.isArray(v) ? v.filter(function (n) { return typeof n === 'number' && Number.isFinite(n); }) : [];
}

function destroyChart(key) {
    if (charts[key]) { charts[key].destroy(); charts[key] = null; }
}

function setChartVisible(id, visible) {
    var el = document.getElementById(id);
    if (el) el.style.visibility = visible ? 'visible' : 'hidden';
}

function showChartBEmpty(message) {
    var holder = document.getElementById('chartB');
    if (!holder) return;
    holder.innerHTML = '';
    var empty = document.createElement('div');
    empty.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:8px;' +
        'height:100%;min-height:280px;color:#94A3B8;font-size:13px;font-weight:500;' +
        'font-family:Inter,Open Sans,sans-serif;';
    empty.textContent = message || 'Tidak ada data untuk ditampilkan';
    holder.appendChild(empty);
}

// Empty / failed payloads clear every chart section instead of leaving stale
// canvas state behind (the source of random blank charts).
function clearChartSections() {
    destroyChart('A'); destroyChart('D'); destroyChart('E'); destroyChart('B');
    setChartVisible('chartA', false);
    setChartVisible('chartD', false);
    setChartVisible('chartE', false);
    showChartBEmpty();
}

// Single render entry point for boot and every filter refresh. Validates the
// payload first, then creates or updates each chart independently so one bad
// section can never take the other charts down.
function renderDashboard(payload, animateKpis) {
    chartState.payload = payload || null;
    window.__DASHBOARD__ = payload || null; // keep download/fullscreen tools in sync

    if (!isValidPayload(payload)) {
        clearChartSections();
        return;
    }

    if (animateKpis) renderKpis(payload.kpis);

    // Each section renders in its own guard so a failure on one chart can
    // never blank or break the others.
    try {
        // Chart A: bar, RKA vs Realisasi.
        var ca = payload.chartA;
        if (ca && Array.isArray(ca.bulan) && Array.isArray(ca.rka) && Array.isArray(ca.realisasi)) {
            var aMax = autoMax(ca.rka.concat(ca.realisasi));
            if (!charts.A) {
                charts.A = new Chart(document.getElementById('chartA'), {
                    type: 'bar',
                    data: {
                        labels: ca.bulan,
                        datasets: [
                            barDataset(ca.rka, GRAY, 'RKA'),
                            barDataset(ca.realisasi, RED, 'Realisasi')
                        ]
                    },
                    options: baseOptions(aMax, 'Jt')
                });
            } else {
                charts.A.data.labels = ca.bulan;
                charts.A.data.datasets[0].data = validData(ca.rka);
                charts.A.data.datasets[1].data = validData(ca.realisasi);
                charts.A.options.scales.y.max = aMax;
                charts.A.options.scales.y.ticks.stepSize = aMax / 5;
                charts.A.update();
            }
            setChartVisible('chartA', true);
        } else {
            destroyChart('A');
            setChartVisible('chartA', false);
        }
    } catch (err) {
        console.error('[dashboard] A render failed:', err);
        destroyChart('A'); setChartVisible('chartA', false);
    }
    try {
        // Charts D + E share the YoY series (chartD payload).
        var cd = payload.chartD;
        if (cd && Array.isArray(cd.bulan) && Array.isArray(cd.tahunLalu) && Array.isArray(cd.tahunSekarang) && Array.isArray(cd.capaian)) {
            var dMax = autoMax(cd.tahunLalu.concat(cd.tahunSekarang));
            if (!charts.D) {
                charts.D = new Chart(document.getElementById('chartD'), {
                    type: 'line',
                    data: {
                        labels: cd.bulan,
                        datasets: [
                            { label: 'Tahun Ini', data: cd.tahunSekarang, borderColor: RED, backgroundColor: RED, pointBackgroundColor: RED, pointRadius: 3, borderWidth: 2, tension: 0.35, yAxisID: 'y' },
                            { label: 'Tahun Sebelum', data: cd.tahunLalu, borderColor: GRAY, backgroundColor: GRAY, pointBackgroundColor: GRAY, pointRadius: 3, borderWidth: 2, tension: 0.35, yAxisID: 'y' },
                            { label: 'Capaian', data: cd.capaian, borderColor: '#3B82F6', pointBackgroundColor: '#3B82F6', pointRadius: 3, borderWidth: 2, tension: 0.35, yAxisID: 'y1' }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
                        resizeDelay: 100,
                        plugins: {
                            legend: { display: false },
                            datalabels: { display: false },
                            tooltip: {
                                callbacks: {
                                    label: function (ctx) {
                                        var v = ctx.parsed.y;
                                        if (ctx.dataset.label === 'Capaian') return ctx.dataset.label + ': ' + v + '%';
                                        return ctx.dataset.label + ': Rp ' + (v * 1000000).toLocaleString('id-ID');
                                    },
                                    footer: SLICER_HINT_FOOTER,
                                },
                                ...SLICER_HINT_STYLE,
                            },
                        },
                        scales: {
                            x: { grid: { display: false }, ticks: Object.assign({}, TICK) },
                            y: { grid: { color: GRID }, min: 0, max: dMax, ticks: Object.assign({}, TICK, { stepSize: dMax / 5, callback: function (v) { return v + 'Jt'; } }) },
                            y1: { position: 'right', grid: { display: false }, min: 0, max: 120, ticks: Object.assign({}, TICK, { stepSize: 30, callback: function (v) { return v + '%'; } }) }
                        },
                    },
                });
            } else {
                charts.D.data.labels = cd.bulan;
                charts.D.data.datasets[0].data = validData(cd.tahunSekarang);
                charts.D.data.datasets[1].data = validData(cd.tahunLalu);
                charts.D.data.datasets[2].data = validData(cd.capaian);
                charts.D.options.scales.y.max = dMax;
                charts.D.options.scales.y.ticks.stepSize = dMax / 5;
                charts.D.update();
            }
            setChartVisible('chartD', true);
            if (!charts.E) {
                charts.E = new Chart(document.getElementById('chartE'), {
                    type: 'bar',
                    data: {
                        labels: cd.bulan,
                        datasets: [
                            barDataset(cd.tahunLalu, GRAY, 'Tahun Sebelum'),
                            barDataset(cd.tahunSekarang, RED, 'Tahun Ini'),
                            { label: 'Capaian', type: 'line', data: cd.capaian, borderColor: '#3B82F6', pointBackgroundColor: '#3B82F6', pointRadius: 3, borderWidth: 2, tension: 0, yAxisID: 'y1' }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
                        resizeDelay: 100,
                        plugins: {
                            legend: { display: false },
                            datalabels: { display: false },
                            tooltip: {
                                callbacks: {
                                    label: function (ctx) {
                                        var v = ctx.parsed.y;
                                        if (ctx.dataset.label === 'Capaian') return ctx.dataset.label + ': ' + v + '%';
                                        return ctx.dataset.label + ': Rp ' + (v * 1000000).toLocaleString('id-ID');
                                    },
                                    footer: SLICER_HINT_FOOTER,
                                },
                                ...SLICER_HINT_STYLE,
                            },
                        },
                        scales: {
                            x: { grid: { display: false }, ticks: Object.assign({}, TICK) },
                            y: { grid: { color: GRID }, min: 0, max: dMax, ticks: Object.assign({}, TICK, { stepSize: dMax / 5, callback: function (v) { return v + 'Jt'; } }) },
                            y1: { position: 'right', grid: { display: false }, min: 0, max: 120, ticks: Object.assign({}, TICK, { stepSize: 30, callback: function (v) { return v + '%'; } }) }
                        },
                    },
                });
            } else {
                charts.E.data.labels = cd.bulan;
                charts.E.data.datasets[0].data = validData(cd.tahunLalu);
                charts.E.data.datasets[1].data = validData(cd.tahunSekarang);
                charts.E.data.datasets[2].data = validData(cd.capaian);
                charts.E.options.scales.y.max = dMax;
                charts.E.options.scales.y.ticks.stepSize = dMax / 5;
                charts.E.update();
            }
            setChartVisible('chartE', true);
        } else {
            destroyChart('D');
            destroyChart('E');
            setChartVisible('chartD', false);
            setChartVisible('chartE', false);
        }
    } catch (err) {
        console.error('[dashboard] DE render failed:', err);
        destroyChart('D'); destroyChart('E'); setChartVisible('chartD', false); setChartVisible('chartE', false);
    }
    try {
        // Chart B: doughnut (pie) or HTML triwulan bars; placeholder when absent.
        var holder = document.getElementById('chartB');
        var cb = payload.chartB;
        if (holder && cb && cb.type === 'pie' && Array.isArray(cb.pie) && cb.pie.length) {
            renderChartBPie(cb.pie); // destroys a previous charts.B instance first
            var note = document.getElementById('chartBNote');
            if (note) note.textContent = cb.note || '';
        } else if (holder && cb && cb.items && cb.items.length) {
            destroyChart('B');
            renderChartB(cb.items); // HTML bars: no canvas instance
            var h2b = holder.closest('.rounded-2xl') ? holder.closest('.rounded-2xl').querySelector('h2') : null;
            if (h2b) h2b.textContent = 'Capaian Realisasi per Triwulan';
            var note2 = document.getElementById('chartBNote');
            if (note2) note2.textContent = cb.note || '';
        } else if (holder && !cb) {
            showChartBEmpty();
        }
    } catch (err) {
        console.error('[dashboard] B render failed:', err);
        if (document.getElementById('chartB')) showChartBEmpty();
    }

    // Idempotent: per-chart onClick is overwritten, wireCursor replaces its
    // own listeners, DOM bindings use onclick properties, toolbar guards on
    // card.__toolbar.
    initDashboardDrill();
    addChartToolbar();
}

function renderChartB(items) {
    const el = document.getElementById('chartB');
    el.innerHTML = items.map((it, i) => `
        <div class="flex-1 flex flex-col items-center justify-end gap-2 h-full cursor-pointer" data-triwulan="${i + 1}">
            <span class="text-[#1E293B] text-[13px] font-bold">${it.pct}%</span>
            <div class="group relative w-[48px] h-[220px] rounded-md ring-0 hover:ring-2 hover:ring-[#10B981]/40 transition-[box-shadow] duration-150">
                <div class="absolute inset-0 rounded-md overflow-hidden bg-[#F8FAFC]">
                    <div class="absolute bottom-0 left-0 right-0 bg-[#10B981]" style="height:${it.pct}%;"></div>
                </div>
                <div class="pointer-events-none absolute left-1/2 -translate-x-1/2 bottom-full mb-2 z-10 hidden group-hover:block whitespace-nowrap rounded-md bg-slate-900 px-3 py-1.5 text-[12px] font-medium text-white shadow-lg">
                    <span class="block">${it.label}: Rp ${(it.realisasi * 1_000_000).toLocaleString('id-ID')} (${it.pct}% Capaian)</span>
                    <span class="block opacity-80">RKA: Rp ${(it.rka * 1_000_000).toLocaleString('id-ID')}</span>
                </div>
            </div>
            <span class="text-[#64748B] text-[11px] font-semibold">${it.label}</span>
        </div>
    `).join('');
}

function renderChartBPie(slices) {
    const holder = document.getElementById('chartB');
    if (!holder) return;
    holder.innerHTML = '';
    const wrapEl = document.createElement('div');
    wrapEl.className = 'relative flex-1 flex items-center justify-center min-h-[310px]';
    const canvas = document.createElement('canvas');
    canvas.id = 'chartBPie';
    canvas.className = 'block max-h-[300px] max-w-full';
    wrapEl.appendChild(canvas);
    holder.appendChild(wrapEl);
    const card = holder.closest('.rounded-2xl');
    const h2 = card ? card.querySelector('h2') : null;
    if (h2) h2.textContent = 'Komposisi Realisasi TF & NTF';
    if (charts.B) { charts.B.destroy(); charts.B = null; }
    charts.B = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: slices.map((s) => s.label),
            datasets: [{
                data: slices.map((s) => s.value),
                backgroundColor: slices.map((s) => s.color),
                borderWidth: 2,
                borderColor: '#ffffff',
                // Slice "explodes" away from center when hovered (pop).
                hoverOffset: 16,
                hoverBorderWidth: 4,
                hoverBorderColor: '#ffffff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '55%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#0F172A',
                        font: { size: 12, weight: 600 },
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 14,
                        boxWidth: 10,
                        boxHeight: 10,
                        // Label = "NTF: Rp 1.570 (58%)" using the slice values.
                        generateLabels: (chart) => {
                            const data = chart.data;
                            const total = data.datasets[0].data.reduce((a, b) => a + b, 0);
                            return data.labels.map((label, i) => {
                                const value = data.datasets[0].data[i];
                                const pct = total ? Math.round((value / total) * 100) : 0;
                                return {
                                    text: `${label}: Rp ${(value * 1_000_000).toLocaleString('id-ID')} (${pct}%)`,
                                    fillStyle: data.datasets[0].backgroundColor[i],
                                    strokeStyle: data.datasets[0].backgroundColor[i],
                                    hidden: false,
                                    index: i,
                                };
                            });
                        },
                    },
                },
                // Data labels with leader lines: the label sits outside the
                // slice and a thin line connects it back to the arc.
                datalabels: {
                    color: '#0F172A',
                    font: { size: 11, weight: 700 },
                    formatter: (value, ctx) => {
                        const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                        const pct = total ? Math.round((value / total) * 100) : 0;
                        return `${ctx.chart.data.labels[ctx.dataIndex]}\n${pct}%`;
                    },
                    anchor: 'end',
                    align: 'end',
                    // Force labels to always show (with leader lines); 'auto'
                    // hides them when the chart is small, which looked like the
                    // labels vanished.
                    display: true,
                    // Leader line styling (plugin draws it between arc and label).
                    clamp: true,
                    textAlign: 'center',
                    padding: 6,
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = total ? Math.round((ctx.parsed / total) * 100) : 0;
                            return ` ${ctx.label}: Rp ${(ctx.parsed * 1_000_000).toLocaleString('id-ID')} (${pct}%)`;
                        },
                    },
                },
            },
        },
    });
}

function renderKpis(kpis) {
    const cards = document.querySelectorAll('[data-kpi]');
    cards.forEach((card) => {
        const idx = Number(card.dataset.kpi);
        const data = kpis[idx];
        if (!data) return;
        card.querySelector('[data-kpi-title]').textContent = data.title;
        const valueEl = card.querySelector('[data-kpi-value]');
        const target = Number(data.value) || 0;
        const prev = Number(card.dataset.prevValue || 0);
        card.dataset.prevValue = String(target);
        // Subtle count-up; all cards share the same clock so they stay in sync.
        const duration = 500;
        const start = performance.now();
        const step = (now) => {
            const t = Math.min(1, (now - start) / duration);
            const eased = 1 - Math.pow(1 - t, 2); // gentle ease-out
            const cur = Math.round(prev + (target - prev) * eased);
            valueEl.textContent = 'Rp' + cur.toLocaleString('id-ID');
            if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
        const cap = card.querySelector('[data-kpi-capaian]');
        if (cap) {
            cap.textContent = data.capaian[0];
            cap.style.color = data.capaian[1];
        }
    });
}

function autoMax(values) {
    const peak = Math.max(...values, 1);
    const raw = peak * 1.08;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const candidates = [1, 2, 2.5, 5, 10].map((m) => m * mag);
    const step = candidates.find((s) => raw / s <= 10) ?? mag * 10;
    return Math.ceil(raw / step) * step;
}

async function refresh() {
    var params = new URLSearchParams();
    document.querySelectorAll('select[data-filter]').forEach(function (sel) {
        params.set(sel.dataset.filter, sel.value);
    });

    // A newer filter selection supersedes any refresh still in flight: abort
    // the previous request so an out-of-order response can never paint stale
    // data over the newest filter.
    if (chartState.controller) chartState.controller.abort();
    var controller = new AbortController();
    chartState.controller = controller;

    // Data is always dynamic: bypass HTTP cache and bust any intermediate
    // cache with a timestamp so every fetch returns fresh values.
    var url = window.__DASHBOARD_URL__ + '?' + params.toString() + '&_=' + Date.now();

    var res;
    try {
        res = await fetch(url, { method: 'GET', cache: 'no-store', signal: controller.signal });
    } catch (err) {
        if (err && err.name === 'AbortError') return; // superseded; a newer refresh owns the screen
        chartState.controller = null;
        return; // network failure: keep the last good charts instead of blanking
    }
    if (controller.signal.aborted || !res.ok) return;
    var payload;
    try {
        payload = await res.json();
    } catch (err) {
        return; // malformed body: keep the last good charts
    }
    if (controller.signal.aborted) return;
    chartState.controller = null;
    renderDashboard(payload, true);
}

window.__refreshDashboard = refresh;

/* ---------------------------------------------------------------------------
   Revenue slicer navigation (charts + cards).

   ONE builder turns the active Revenue Overview filters into Data Revenue
   query params, so every visual (chart bars/points/slices, triwulan bars,
   cards) drills down through the same contract.

   Param names and per-option values come from the server contract on
   #revenue-filter-card (`data-revenue-param`, `data-revenue`, `data-period-*`),
   which already validated each overview filter value against the finance
   master data — so a slicer can never open an empty page, and nothing here
   duplicates the mapping.
--------------------------------------------------------------------------- */
const REVENUE_DIMENSIONS = [
    // slicer dimension -> overview filter, canonical param, period fallback
    { dim: 'year', filter: 'tahun', param: 'tahun[]', period: true },
    { dim: 'month', filter: null, param: 'bulan[]' },
    { dim: 'unit', filter: 'direktorat', param: 'org[]' },
    { dim: 'pp', filter: 'kode_pp', param: 'pp[]' },
    { dim: 'account', filter: null, param: 'account[]' },
    { dim: 'revenueType', filter: 'tipe', param: 'jenis[]' },
];

function revenueFilterCard() {
    return document.getElementById('revenue-filter-card');
}

// The Tipe option contract for one value (a slice may cover several types).
function revenueTypesFor(tipeValue) {
    const card = revenueFilterCard();
    const sel = card && card.querySelector('select[data-filter="tipe"]');
    const opt = sel && [...sel.options].find((o) => o.value === tipeValue);
    const values = String((opt && opt.dataset.revenue) || '')
        .split(',').map((v) => v.trim()).filter(Boolean);
    return values.length ? values : null;
}

function revenueDimensions() {
    const card = revenueFilterCard();
    const periodYear = card ? (card.dataset.periodYear || '') : '';
    const out = {};
    REVENUE_DIMENSIONS.forEach((spec) => {
        const sel = (spec.filter && card)
            ? card.querySelector('select[data-filter="' + spec.filter + '"]')
            : null;
        let param = spec.param;
        if (spec.dim === 'month' && card && card.dataset.revenueMonthParam) param = card.dataset.revenueMonthParam;
        if (spec.dim === 'account' && card && card.dataset.revenueAccountParam) param = card.dataset.revenueAccountParam;
        if (sel && sel.dataset.revenueParam) param = sel.dataset.revenueParam;
        let values = [];
        if (sel) {
            const opt = sel.options[sel.selectedIndex];
            // One overview option may map to several revenue values ('NTF').
            values = String((opt && opt.dataset.revenue) || '')
                .split(',').map((v) => v.trim()).filter(Boolean);
            // No usable year on the filter? Fall back to the active period.
            if (spec.period && !values.length && periodYear) values = [periodYear];
        }
        out[spec.dim] = { param, values };
    });
    return out;
}

// Year the "current" series belongs to: the selected year, else the period.
function revenueBaseYear() {
    const y = parseInt(revenueDimensions().year.values[0] || '', 10);
    return Number.isFinite(y) ? y : null;
}

// Active filters + click overrides -> Data Revenue query string.
// overrides: { year, month, unit, pp, account, revenueType }; a click wins for
// the dimension it sets. Months are NUMBERS (see monthNumber).
function revenueFilterQuery(overrides) {
    const o = overrides || {};
    const dims = revenueDimensions();
    const params = new URLSearchParams();
    REVENUE_DIMENSIONS.forEach((spec) => {
        let values = dims[spec.dim].values;
        if (Object.prototype.hasOwnProperty.call(o, spec.dim)) {
            const raw = o[spec.dim];
            values = (Array.isArray(raw) ? raw : [raw])
                .filter((v) => v !== null && v !== undefined && v !== '');
        }
        if (spec.dim === 'year') {
            values = values
                .map((v) => (Number.isFinite(Number(v)) ? String(Number(v)) : null))
                .filter(Boolean);
        }
        values.forEach((v) => params.append(dims[spec.dim].param, String(v)));
    });
    return params;
}

function revenueDataUrl(overrides) {
    const base = window.__REVENUE_DATA_URL__ || '/dashboard/revenue/data/';
    const qs = revenueFilterQuery(overrides).toString();
    return qs ? base + '?' + qs : base;
}

// The reusable slicer entry point used by every chart and horizontal card link.
function navigateToRevenueData(overrides) {
    window.location.href = revenueDataUrl(overrides);
}

// Shared with revenue-filter.js so the card hrefs and the chart drill-down are
// built by the very same code.
window.revenueFilterQuery = revenueFilterQuery;
window.revenueBaseYear = revenueBaseYear;
window.revenueDataUrl = revenueDataUrl;
window.navigateToRevenueData = navigateToRevenueData;

function initDashboardDrill() {
    const wireCursor = (chart, intersect = true) => {
        const canvas = chart.canvas;
        const setCursor = (e) => {
            const els = chart.getElementsAtEventForMode(e, 'nearest', { intersect }, false);
            canvas.style.cursor = els.length ? 'pointer' : '';
        };
        if (canvas.__wfLeave) canvas.removeEventListener('mouseleave', canvas.__wfLeave);
        if (canvas.__wfMove) canvas.removeEventListener('mousemove', canvas.__wfMove);
        var onMove = setCursor;
        var onLeave = function () { canvas.style.cursor = ''; };
        canvas.__wfMove = onMove;
        canvas.__wfLeave = onLeave;
        canvas.addEventListener('mousemove', onMove);
        canvas.addEventListener('mouseleave', onLeave);
    };

    // Chart A (Realisasi vs RKA per Bulan): every month bar is a slicer —
    // clicked month (as a NUMBER) + the filters active on this page.
    if (charts.A) {
        charts.A.options.onClick = (evt, elements) => {
            if (!elements.length) return;
            const el = elements[0];
            navigateToRevenueData({ month: monthNumber(charts.A.data.labels[el.index], el.index) });
        };
        wireCursor(charts.A);
    }

    /* Charts D (line) and E (bar) share the YoY series, so they share ONE click
       contract: 'Tahun Sebelum' -> previous year, 'Tahun Ini' / 'Capaian' ->
       the year currently active on the page. */
    const wireYoySlicer = (chart, intersect) => {
        if (!chart) return;
        chart.options.onClick = (evt, elements) => {
            const els = (elements && elements.length)
                ? elements
                : chart.getElementsAtEventForMode(evt, 'nearest', { intersect }, true);
            if (!els.length) return;
            const el = els[0];
            const label = chart.data.datasets[el.datasetIndex].label;
            const overrides = { month: monthNumber(chart.data.labels[el.index], el.index) };
            const base = revenueBaseYear();
            if (label === 'Tahun Sebelum' && base !== null) overrides.year = base - 1;
            navigateToRevenueData(overrides);
        };
        wireCursor(chart, intersect);
    };
    wireYoySlicer(charts.D, false);
    wireYoySlicer(charts.E, true);

    // Pie (Komposisi per Tipe): a slice maps to the same Tipe option the filter
    // card offers, so its revenue type(s) come from that option's contract
    // ('NTF' covers both NTF categories, 'TF' just TF).
    if (charts.B) {
        charts.B.options.onClick = (evt, elements) => {
            if (!elements.length) return;
            const types = revenueTypesFor(charts.B.data.labels[elements[0].index]);
            if (types) navigateToRevenueData({ revenueType: types });
        };
        wireCursor(charts.B);
    }

    // Triwulan bars: a quarter expands to its three months — the tables accept
    // several month values, so the whole quarter is filtered in one click.
    const chartB = document.getElementById('chartB');
    if (chartB) {
        chartB.onclick = (e) => {
            const wrap = e.target.closest('[data-triwulan]');
            if (!wrap) return;
            const q = parseInt(wrap.dataset.triwulan, 10);
            if (!(q >= 1 && q <= 4)) return;
            const first = (q - 1) * 3 + 1;
            navigateToRevenueData({ month: [first, first + 1, first + 2] });
        };
    }
}

// ---------------------------------------------------------------------------
// Chart toolbar: fullscreen + download (PNG/JPG) for each chart card.
// ---------------------------------------------------------------------------
const CHART_TOOLBAR_CSS = `
.chart-toolbar { position: absolute; top: 10px; right: 10px; z-index: 20; display: flex; gap: 6px; opacity: 0; transition: opacity .2s ease; }
.chart-card:hover .chart-toolbar { opacity: 1; }
.chart-toolbar button {
    display: inline-flex; align-items: center; gap: 4px;
    background: rgba(15, 23, 42, .85); color: #fff;
    border: 0; border-radius: 8px; padding: 5px 10px;
    font-size: 11px; font-weight: 600; cursor: pointer;
    font-family: 'Inter', 'Open Sans', ui-sans-serif, system-ui, sans-serif;
    transition: background .15s ease, transform .15s ease;
}
.chart-toolbar button:hover { background: #EB3237; transform: translateY(-1px); }
.chart-fullscreen { position: fixed; inset: 0; z-index: 10000; background: #fff; padding: 24px; display: flex; flex-direction: column; }
.chart-fullscreen .fs-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.chart-fullscreen .fs-title { font-size: 16px; font-weight: 700; color: #0F172A; font-family: 'Inter','Open Sans',sans-serif; }
.chart-fullscreen .fs-body { flex: 1; min-height: 0; position: relative; }
.chart-fullscreen .fs-close {
    background: #EB3237; color: #fff; border: 0; border-radius: 8px; padding: 6px 14px;
    font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit;
}
`;

function injectToolbarCss() {
    if (document.getElementById('chart-toolbar-style')) return;
    const st = document.createElement('style');
    st.id = 'chart-toolbar-style';
    st.textContent = CHART_TOOLBAR_CSS;
    document.head.appendChild(st);
}

function getChartForCanvas(canvas) {
    // charts map holds instances by id; chartBPie lives under charts.B
    if (canvas.id === 'chartBPie') return charts.B;
    return charts[canvas.id] || null;
}

function chartTitleFor(canvas) {
    const card = canvas.closest('.rounded-2xl, .chart-card');
    const h2 = card && card.querySelector('h2');
    return (h2 && h2.textContent.trim()) || canvas.id || 'chart';
}

function renderChartBToCanvas(items) {
    // Re-render the CSS bar chart (chartB in bars mode) onto a temp canvas.
    const canvas = document.createElement('canvas');
    canvas.width = 1000; canvas.height = 500;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const maxPct = Math.max(...items.map(i => i.pct), 1);
    const chartW = canvas.width - 120, chartH = canvas.height - 90;
    const left = 60, top = 40, bottom = canvas.height - 40;
    items.forEach((it, i) => {
        const slot = chartW / items.length;
        const x = left + i * slot + slot * 0.2;
        const w = slot * 0.6;
        const h = (it.pct / 120) * chartH; // scale to 120% max
        const y = bottom - h;
        ctx.fillStyle = '#10B981';
        ctx.fillRect(x, y, w, h);
        ctx.fillStyle = '#1E293B';
        ctx.font = 'bold 16px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(it.pct + '%', x + w / 2, y - 8);
        ctx.fillStyle = '#64748B';
        ctx.font = '13px Inter, sans-serif';
        ctx.fillText(it.label, x + w / 2, bottom + 22);
    });
    ctx.fillStyle = '#94A3B8';
    ctx.font = '12px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('Capaian Realisasi per Triwulan (%)', left, top - 10);
    return canvas;
}

function downloadChart(canvas, format) {
    const isChartB = canvas.id === 'chartB' && !document.getElementById('chartBPie');
    let source = canvas;
    if (isChartB) {
        // bars mode: no canvas exists; render from current payload
        const items = (window.__DASHBOARD__ && window.__DASHBOARD__.chartB && window.__DASHBOARD__.chartB.type !== 'pie')
            ? window.__DASHBOARD__.chartB.items
            : null;
        if (!items) return;
        source = renderChartBToCanvas(items);
    }
    const ext = format === 'jpg' ? 'jpeg' : 'png';
    const quality = format === 'jpg' ? 0.92 : undefined;
    const dataUrl = source.toDataURL('image/' + ext, quality);
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = chartTitleFor(canvas).replace(/[^a-z0-9]+/gi, '_') + '.' + (format === 'jpg' ? 'jpg' : 'png');
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function addChartToolbar() {
    injectToolbarCss();
    document.querySelectorAll('#chartA, #chartD, #chartE').forEach((canvas) => {
        if (canvas.closest('.chart-card')) return;
        const card = canvas.closest('.rounded-2xl');
        if (!card || card.__toolbar) return;
        card.classList.add('chart-card');
        card.style.position = 'relative';
        const tb = document.createElement('div');
        tb.className = 'chart-toolbar';
        tb.innerHTML = `
            <button data-action="fullscreen" title="Fullscreen">⛶ Fullscreen</button>
            <button data-action="png" title="Download PNG">⬇ PNG</button>
            <button data-action="jpg" title="Download JPG">⬇ JPG</button>
        `;
        card.appendChild(tb);
        card.__toolbar = true;
        tb.addEventListener('click', (e) => {
            const btn = e.target.closest('button');
            if (!btn) return;
            const action = btn.dataset.action;
            if (action === 'fullscreen') toggleChartFullscreen(canvas, card);
            else if (action === 'png') downloadChart(canvas, 'png');
            else if (action === 'jpg') downloadChart(canvas, 'jpg');
        });
    });
    // Chart B card (pie or bars)
    const bCanvas = document.getElementById('chartBPie');
    const bCard = document.getElementById('chartB')?.closest('.rounded-2xl');
    if (bCard && !bCard.__toolbar) {
        bCard.classList.add('chart-card');
        bCard.style.position = 'relative';
        const tb = document.createElement('div');
        tb.className = 'chart-toolbar';
        tb.innerHTML = `
            <button data-action="fullscreen" title="Fullscreen">⛶ Fullscreen</button>
            <button data-action="png" title="Download PNG">⬇ PNG</button>
            <button data-action="jpg" title="Download JPG">⬇ JPG</button>
        `;
        bCard.appendChild(tb);
        bCard.__toolbar = true;
        tb.addEventListener('click', (e) => {
            const btn = e.target.closest('button');
            if (!btn) return;
            const action = btn.dataset.action;
            const target = document.getElementById('chartBPie') || document.getElementById('chartB');
            if (action === 'fullscreen') toggleChartFullscreen(target, bCard);
            else if (action === 'png') downloadChart(target, 'png');
            else if (action === 'jpg') downloadChart(target, 'jpg');
        });
    }
}

function toggleChartFullscreen(canvas, card) {
    const existing = document.querySelector('.chart-fullscreen');
    if (existing) {
        document.exitFullscreen && document.exitFullscreen();
        existing.remove();
        return;
    }
    const title = chartTitleFor(canvas);
    const fs = document.createElement('div');
    fs.className = 'chart-fullscreen';
    fs.innerHTML = `
        <div class="fs-header">
            <span class="fs-title">${title}</span>
            <div style="display:flex;gap:8px;">
                <button data-dl="png" class="fs-close" style="background:#0F172A;">⬇ PNG</button>
                <button data-dl="jpg" class="fs-close" style="background:#0F172A;">⬇ JPG</button>
                <button data-close class="fs-close">✕ Tutup</button>
            </div>
        </div>
        <div class="fs-body"></div>
    `;
    document.body.appendChild(fs);
    const body = fs.querySelector('.fs-body');
    // Move the chart into fullscreen: clone the canvas and rebuild the chart
    // with responsive options so it fills the fullscreen body.
    const clone = canvas.cloneNode(false);
    clone.id = canvas.id + '-fs';
    clone.style.width = '100%';
    clone.style.height = '100%';
    body.appendChild(clone);
    const srcChart = getChartForCanvas(canvas);
    const fsCharts = [];
    if (canvas.id === 'chartB' && !document.getElementById('chartBPie')) {
        // bars mode: render CSS bars into a canvas at fullscreen size
        const items = (window.__DASHBOARD__ && window.__DASHBOARD__.chartB && window.__DASHBOARD__.chartB.items) || [];
        const tmp = renderChartBToCanvas(items);
        clone.width = body.clientWidth || 1200;
        clone.height = body.clientHeight || 600;
        clone.getContext('2d').drawImage(tmp, 0, 0, clone.width, clone.height);
    } else if (srcChart) {
        // Rebuild sharing the live config object graph (functions intact),
        // overriding the sizing so the chart fills the fullscreen body.
        const cfg = srcChart.config;
        const opts = cfg.options || {};
        opts.responsive = true;
        opts.maintainAspectRatio = false;
        const chart = new Chart(clone, cfg);
        fsCharts.push(chart);
    }
    // Resize the chart when the fullscreen container resizes (window resize
    // while in fullscreen, or container growth).
    const ro = new ResizeObserver(() => {
        fsCharts.forEach((c) => c.resize());
        if (canvas.id === 'chartB' && !document.getElementById('chartBPie')) {
            // redraw the bars canvas at new size
            const items = (window.__DASHBOARD__ && window.__DASHBOARD__.chartB && window.__DASHBOARD__.chartB.items) || [];
            const tmp = renderChartBToCanvas(items);
            const c = clone;
            c.width = body.clientWidth || 1200;
            c.height = body.clientHeight || 600;
            c.getContext('2d').drawImage(tmp, 0, 0, c.width, c.height);
        }
    });
    ro.observe(body);
    // fullscreen API on the container
    if (fs.requestFullscreen) fs.requestFullscreen();
    fs.querySelector('[data-close]').addEventListener('click', () => {
        if (document.fullscreenElement) document.exitFullscreen();
        fs.remove();
    });
    fs.querySelectorAll('[data-dl]').forEach((b) => {
        b.addEventListener('click', () => downloadChart(clone, b.dataset.dl));
    });
}

document.addEventListener('DOMContentLoaded', function () {
    initSidebar();

    var d = window.__DASHBOARD__;
    if (d) renderDashboard(d, false);
});

function initSidebar() {
    const toggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    const content = document.getElementById('content');
    const scrim = document.getElementById('sidebar-scrim');
    if (!toggle || !sidebar) return;

    const open = () => {
        sidebar.classList.add('sidebar-open');
        if (content) content.classList.add('sidebar-pushed');
        if (scrim) scrim.classList.add('scrim-visible');
        localStorage.setItem('sidebar-open', '1');
    };
    const close = () => {
        sidebar.classList.remove('sidebar-open');
        if (content) content.classList.remove('sidebar-pushed');
        if (scrim) scrim.classList.remove('scrim-visible');
        localStorage.setItem('sidebar-open', '0');
    };

    if (localStorage.getItem('sidebar-open') === '1') {
        document.body.classList.add('no-transition');
        open();
        requestAnimationFrame(() => requestAnimationFrame(() => {
            document.body.classList.remove('no-transition');
        }));
    }

    toggle.addEventListener('click', () => {
        sidebar.classList.contains('sidebar-open') ? close() : open();
    });

    if (scrim) scrim.addEventListener('click', close);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') close();
    });
}
