import Chart from 'chart.js/auto';

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
        tooltip: {
            callbacks: {
                label: (ctx) => {
                    const v = ctx.parsed.y;
                    if (unit === 'Jt') return `${ctx.dataset.label}: Rp ${(v * 1_000_000).toLocaleString('id-ID')}`;
                    return `${ctx.dataset.label}: ${v}${unit}`;
                },
            },
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

const MONTHS_FULL = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];

const charts = {};

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
    const el = document.getElementById('chartB');
    el.innerHTML = '<div class="relative flex-1 flex items-center justify-center min-h-[310px]"><canvas id="chartBPie" class="block max-h-[300px] max-w-full"></canvas></div>';
    const card = el.closest('.rounded-2xl');
    const h2 = card?.querySelector('h2');
    if (h2) h2.textContent = 'Komposisi Realisasi per Tipe';
    const canvas = document.getElementById('chartBPie');
    if (charts.B) charts.B.destroy();
    charts.B = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: slices.map((s) => s.label),
            datasets: [{
                data: slices.map((s) => s.value),
                backgroundColor: slices.map((s) => s.color),
                borderWidth: 2,
                borderColor: '#ffffff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '55%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#0F172A', font: { size: 12, weight: 600 }, usePointStyle: true, pointStyle: 'circle', padding: 14 },
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
        card.querySelector('[data-kpi-value]').textContent = 'Rp' + Number(data.value).toLocaleString('id-ID');
        const cap = card.querySelector('[data-kpi-capaian]');
        if (cap) {
            cap.textContent = data.capaian[0];
            cap.style.color = data.capaian[1];
        }
    });
}

function applyPayload(payload) {
    renderKpis(payload.kpis);

    charts.A.data.labels = payload.chartA.bulan;
    charts.A.data.datasets[0].data = payload.chartA.rka;
    charts.A.data.datasets[1].data = payload.chartA.realisasi;
    charts.A.options.scales.y.max = autoMax([...payload.chartA.rka, ...payload.chartA.realisasi]);
    charts.A.options.scales.y.ticks.stepSize = charts.A.options.scales.y.max / 5;
    charts.A.update();

    if (payload.chartB.type === 'pie') {
        renderChartBPie(payload.chartB.pie);
    } else {
        if (charts.B) charts.B.destroy();
        charts.B = null;
        renderChartB(payload.chartB.items);
        const h2 = document.getElementById('chartB').closest('.rounded-2xl')?.querySelector('h2');
        if (h2) h2.textContent = 'Capaian Realisasi per Triwulan';
    }
    document.getElementById('chartBNote').textContent = payload.chartB.note;

    charts.D.data.labels = payload.chartD.bulan;
    charts.D.data.datasets[0].data = payload.chartD.tahunLalu;
    charts.D.data.datasets[1].data = payload.chartD.tahunSekarang;
    charts.D.data.datasets[2].data = payload.chartD.capaian;
    charts.D.options.scales.y.max = autoMax([...payload.chartD.tahunLalu, ...payload.chartD.tahunSekarang]);
    charts.D.options.scales.y.ticks.stepSize = charts.D.options.scales.y.max / 5;
    charts.D.update();

    if (charts.E) {
        charts.E.data.labels = payload.chartD.bulan;
        charts.E.data.datasets[0].data = payload.chartD.tahunLalu;
        charts.E.data.datasets[1].data = payload.chartD.tahunSekarang;
        charts.E.data.datasets[2].data = payload.chartD.capaian;
        charts.E.options.scales.y.max = autoMax([...payload.chartD.tahunLalu, ...payload.chartD.tahunSekarang]);
        charts.E.options.scales.y.ticks.stepSize = charts.E.options.scales.y.max / 5;
        charts.E.update();
    }
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
    const params = new URLSearchParams();
    document.querySelectorAll('select[data-filter]').forEach((sel) => {
        params.set(sel.dataset.filter, sel.value);
    });
    const res = await fetch(window.__DASHBOARD_URL__ + '?' + params.toString());
    if (!res.ok) return;
    const payload = await res.json();
    applyPayload(payload);
}

function currentGlobalFilters() {
    const f = {};
    document.querySelectorAll('select[data-filter]').forEach((sel) => {
        f[sel.dataset.filter] = sel.value;
    });
    return f;
}

function drillThrough(extra) {
    const f = currentGlobalFilters();
    const params = new URLSearchParams();
    for (const k of ['tipe', 'direktorat', 'kode_pp', 'tahun']) {
        if (f[k]) params.set(k, f[k]);
    }
    for (const [k, v] of Object.entries(extra)) {
        if (v !== null && v !== undefined) params.set(k, v);
    }
    window.location.href = window.__DETAIL_URL__ + '?' + params.toString();
}

function initDashboardDrill() {
    const wireCursor = (chart, intersect = true) => {
        const canvas = chart.canvas;
        const setCursor = (e) => {
            const els = chart.getElementsAtEventForMode(e, 'nearest', { intersect }, false);
            canvas.style.cursor = els.length ? 'pointer' : '';
        };
        canvas.addEventListener('mousemove', setCursor);
        canvas.addEventListener('mouseleave', () => { canvas.style.cursor = ''; });
    };

    if (charts.A) {
        charts.A.options.onClick = (evt, elements) => {
            if (!elements.length) return;
            const month = MONTHS_FULL[elements[0].index];
            if (month) drillThrough({ bulan: month });
        };
        wireCursor(charts.A);
    }

    if (charts.D) {
        charts.D.options.onClick = (evt) => {
            const els = charts.D.getElementsAtEventForMode(evt, 'nearest', { intersect: false }, true);
            if (!els.length) return;
            const el = els[0];
            const month = MONTHS_FULL[el.index];
            if (!month) return;
            const label = charts.D.data.datasets[el.datasetIndex].label;
            if (label === 'Tahun Sebelum') {
                const tahun = currentGlobalFilters().tahun;
                if (tahun === 'Semua') {
                    drillThrough({ bulan: month, tahun: 'Semua' });
                } else {
                    const n = parseInt(tahun, 10);
                    const years = [...document.querySelectorAll('select[data-filter="tahun"] option')]
                        .map((o) => parseInt(o.value, 10))
                        .filter((v) => Number.isFinite(v));
                    const min = Math.min(...years);
                    const prev = Number.isFinite(n) ? Math.max(min, n - 1) : n;
                    drillThrough({ bulan: month, tahun: prev });
                }
            } else {
                drillThrough({ bulan: month });
            }
        };
        wireCursor(charts.D, false);
    }

    if (charts.E) {
        charts.E.options.onClick = (evt, elements) => {
            if (!elements.length) return;
            const el = elements[0];
            const month = MONTHS_FULL[el.index];
            if (!month) return;
            const label = charts.E.data.datasets[el.datasetIndex].label;
            if (label === 'Tahun Sebelum') {
                const tahun = currentGlobalFilters().tahun;
                if (tahun === 'Semua') {
                    drillThrough({ bulan: month, tahun: 'Semua' });
                } else {
                    const n = parseInt(tahun, 10);
                    const years = [...document.querySelectorAll('select[data-filter="tahun"] option')]
                        .map((o) => parseInt(o.value, 10))
                        .filter((v) => Number.isFinite(v));
                    const min = Math.min(...years);
                    const prev = Number.isFinite(n) ? Math.max(min, n - 1) : n;
                    drillThrough({ bulan: month, tahun: prev });
                }
            } else {
                drillThrough({ bulan: month });
            }
        };
        wireCursor(charts.E);
    }

    document.querySelectorAll('[data-kpi]').forEach((card) => {
        const period = card.dataset.period;
        if (!period) return;
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => {
            if (period === 'tahun') {
                drillThrough({});
            } else if (period === 'agustus') {
                drillThrough({ bulan: 'Agustus' });
            }
        });
    });

    const chartB = document.getElementById('chartB');
    if (chartB) {
        chartB.addEventListener('click', (e) => {
            const wrap = e.target.closest('[data-triwulan]');
            if (wrap) drillThrough({ triwulan: wrap.dataset.triwulan });
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initSidebar();

    const d = window.__DASHBOARD__;

    if (d) {
        charts.A = new Chart(document.getElementById('chartA'), {
            type: 'bar',
            data: {
                labels: d.chartA.bulan,
                datasets: [
                    barDataset(d.chartA.rka, GRAY, 'RKA'),
                    barDataset(d.chartA.realisasi, RED, 'Realisasi'),
                ],
            },
            options: baseOptions(autoMax([...d.chartA.rka, ...d.chartA.realisasi]), 'Jt'),
        });

        if (d.chartB.type === 'pie') {
            renderChartBPie(d.chartB.pie);
        } else {
            renderChartB(d.chartB.items);
        }

        const dMax = autoMax([...d.chartD.tahunLalu, ...d.chartD.tahunSekarang]);
        charts.D = new Chart(document.getElementById('chartD'), {
            type: 'line',
            data: {
                labels: d.chartD.bulan,
                datasets: [
                    { label: 'Tahun Ini', data: d.chartD.tahunSekarang, borderColor: RED, backgroundColor: RED, pointBackgroundColor: RED, pointRadius: 3, borderWidth: 2, tension: 0.35, yAxisID: 'y' },
                    { label: 'Tahun Sebelum', data: d.chartD.tahunLalu, borderColor: GRAY, backgroundColor: GRAY, pointBackgroundColor: GRAY, pointRadius: 3, borderWidth: 2, tension: 0.35, yAxisID: 'y' },
                    { label: 'Capaian', data: d.chartD.capaian, borderColor: '#3B82F6', pointBackgroundColor: '#3B82F6', pointRadius: 3, borderWidth: 2, tension: 0.35, yAxisID: 'y1' },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
                resizeDelay: 100,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.parsed.y;
                                if (ctx.dataset.label === 'Capaian') return `${ctx.dataset.label}: ${v}%`;
                                return `${ctx.dataset.label}: Rp ${(v * 1_000_000).toLocaleString('id-ID')}`;
                            },
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false }, ticks: { ...TICK } },
                    y: { grid: { color: GRID }, min: 0, max: dMax, ticks: { ...TICK, stepSize: dMax / 5, callback: (v) => v + 'Jt' } },
                    y1: { position: 'right', grid: { display: false }, min: 0, max: 120, ticks: { ...TICK, stepSize: 30, callback: (v) => v + '%' } },
                },
            },
        });

        charts.E = new Chart(document.getElementById('chartE'), {
            type: 'bar',
            data: {
                labels: d.chartD.bulan,
                datasets: [
                    barDataset(d.chartD.tahunLalu, GRAY, 'Tahun Sebelum'),
                    barDataset(d.chartD.tahunSekarang, RED, 'Tahun Ini'),
                    { label: 'Capaian', type: 'line', data: d.chartD.capaian, borderColor: '#3B82F6', pointBackgroundColor: '#3B82F6', pointRadius: 3, borderWidth: 2, tension: 0, yAxisID: 'y1' },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
                resizeDelay: 100,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.parsed.y;
                                if (ctx.dataset.label === 'Capaian') return `${ctx.dataset.label}: ${v}%`;
                                return `${ctx.dataset.label}: Rp ${(v * 1_000_000).toLocaleString('id-ID')}`;
                            },
                        },
                    },
                },
                scales: {
                    x: { grid: { display: false }, ticks: { ...TICK } },
                    y: { grid: { color: GRID }, min: 0, max: dMax, ticks: { ...TICK, stepSize: dMax / 5, callback: (v) => v + 'Jt' } },
                    y1: { position: 'right', grid: { display: false }, min: 0, max: 120, ticks: { ...TICK, stepSize: 30, callback: (v) => v + '%' } },
                },
            },
        });

        document.querySelectorAll('select[data-filter]').forEach((sel) => {
            sel.addEventListener('change', refresh);
        });

        initDashboardDrill();
    }
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
