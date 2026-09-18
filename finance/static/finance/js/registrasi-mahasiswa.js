/* Registrasi Mahasiswa: mixed chart (quota/registration lines, BPP bars),
 * dependent program dropdown, and in-place refresh on "Terapkan".
 *
 * The aggregation is entirely server-side; this file only renders what the
 * backend returns, so the page and the JSON endpoint can never disagree.
 */
(function () {
    'use strict';

    var form = document.getElementById('regm-filter-form');
    var chartEl = document.getElementById('regm-chart');
    if (!form || !chartEl) return;

    var dataUrl = form.dataset.dataUrl;
    var programsUrl = form.dataset.programsUrl;
    var facultySel = document.getElementById('regm-faculty');
    var programSel = document.getElementById('regm-program');
    var resetBtn = document.getElementById('regm-reset-btn');
    var body = document.getElementById('regm-body');
    var empty = document.getElementById('regm-empty');
    var titleEl = document.getElementById('regm-chart-title');

    // Dashboard palette: primary red for the tariff bars, blues for the two
    // student-count lines, so BPP reads as a different measure on its own axis.
    var COLOR_QUOTA = '#3B82F6';
    var COLOR_REGISTRATION = '#1E3A8A';
    var COLOR_TARIFF = '#C8102E';

    var chart = null;

    function rupiah(v) {
        return 'Rp' + Number(v).toLocaleString('id-ID');
    }

    function students(v) {
        return Number(v).toLocaleString('id-ID') + ' mahasiswa';
    }

    function buildOption(payload) {
        var series = payload.series || {};
        var out = [];
        if (Array.isArray(series.quota)) {
            out.push({
                name: 'Kuota', type: 'line', smooth: true, symbol: 'circle', symbolSize: 7,
                yAxisIndex: 0, data: series.quota, lineStyle: { width: 3, color: COLOR_QUOTA },
                itemStyle: { color: COLOR_QUOTA },
            });
        }
        if (Array.isArray(series.registration)) {
            out.push({
                name: 'Registrasi', type: 'line', smooth: true, symbol: 'circle', symbolSize: 7,
                yAxisIndex: 0, data: series.registration, lineStyle: { width: 3, color: COLOR_REGISTRATION },
                itemStyle: { color: COLOR_REGISTRATION },
            });
        }
        if (Array.isArray(series.tariff)) {
            out.push({
                name: 'Tarif BPP', type: 'bar', yAxisIndex: 1, data: series.tariff,
                barMaxWidth: 44, itemStyle: { color: COLOR_TARIFF, borderRadius: [4, 4, 0, 0] },
            });
        }
        return {
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                formatter: function (params) {
                    var html = '<b>' + params[0].axisValue + '</b>';
                    params.forEach(function (p) {
                        if (p.value === null || p.value === undefined || p.value === '-') return;
                        var v = p.seriesType === 'bar' ? rupiah(p.value) : students(p.value);
                        html += '<br/>' + p.marker + p.seriesName + ': ' + v;
                    });
                    return html;
                },
            },
            legend: { data: out.map(function (s) { return s.name; }), bottom: 0, icon: 'roundRect', textStyle: { color: '#6B7280' } },
            grid: { left: 72, right: 88, top: 30, bottom: 56 },
            xAxis: {
                type: 'category', data: payload.years || [], boundaryGap: true,
                axisLine: { lineStyle: { color: '#E5E7EB' } },
                axisLabel: { color: '#6B7280' },
            },
            yAxis: [
                {
                    type: 'value', name: 'Jumlah Mahasiswa',
                    nameTextStyle: { color: '#9CA3AF', align: 'left' },
                    splitLine: { lineStyle: { color: '#F0F1F3' } },
                    axisLabel: { color: '#6B7280', formatter: function (v) { return Number(v).toLocaleString('id-ID'); } },
                },
                {
                    type: 'value', name: 'Tarif BPP (Rp)',
                    nameTextStyle: { color: '#9CA3AF', align: 'right' },
                    splitLine: { show: false },
                    axisLabel: {
                        color: '#6B7280',
                        formatter: function (v) {
                            if (v >= 1000000) return (v / 1000000).toLocaleString('id-ID') + ' jt';
                            return Number(v).toLocaleString('id-ID');
                        },
                    },
                },
            ],
            series: out,
        };
    }

    function renderChart(payload) {
        if (!payload.has_data || !payload.years || !payload.years.length) {
            if (chart) { chart.dispose(); chart = null; }
            return;
        }
        if (!chart) chart = echarts.init(chartEl);
        chart.setOption(buildOption(payload), true);
    }

    function setText(id, text) {
        var el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function renderSummary(summary) {
        if (!summary) return;
        // Formatted server-side (summary.disp) so this and the first paint agree.
        var d = summary.disp || {};
        setText('regm-s-quota', d.quota);
        setText('regm-s-registration', d.registration);
        setText('regm-s-year', summary.year === null ? '-' : summary.year);
        setText('regm-s-year-2', summary.year === null ? '-' : summary.year);
        setText('regm-s-achievement', d.achievement);
        setText('regm-s-tariff', d.tariff_average);
    }

    function renderTable(rows) {
        var tbody = document.getElementById('regm-table-body');
        if (!tbody || !Array.isArray(rows)) return;
        var html = '';
        rows.forEach(function (r) {
            var diffClass = r.difference > 0 ? ' regm-pos' : (r.difference < 0 ? ' regm-neg' : '');
            // Server-formatted strings (r.disp) so this matches the first paint.
            var d = r.disp || {};
            html += '<tr' + (r.programs ? '' : ' class="regm-row-empty"') + '>'
                + '<td>' + r.year + '</td>'
                + '<td class="regm-num">' + d.quota + '</td>'
                + '<td class="regm-num">' + d.registration + '</td>'
                + '<td class="regm-num' + diffClass + '">' + d.difference + '</td>'
                + '<td class="regm-num">' + d.achievement + '</td>'
                + '<td class="regm-num">' + d.tariff_average + '</td>'
                + '</tr>';
        });
        tbody.innerHTML = html;
    }

    function render(payload) {
        var has = !!payload.has_data;
        if (body) body.hidden = !has;
        if (empty) empty.hidden = has;
        if (!has) {
            if (chart) { chart.dispose(); chart = null; }
            return;
        }
        if (titleEl) {
            titleEl.textContent = 'Tren Kuota, Registrasi, dan Tarif BPP'
                + (payload.chart_label ? ' ' + payload.chart_label : '');
        }
        renderSummary(payload.summary);
        renderTable(payload.table);
        renderChart(payload);
    }

    function load() {
        var qs = new URLSearchParams(new FormData(form)).toString();
        // Keep the URL shareable so a filtered view can be bookmarked.
        history.replaceState(null, '', form.action + (qs ? '?' + qs : ''));
        fetch(dataUrl + (qs ? '?' + qs : ''), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); })
            .then(render)
            .catch(function () { /* keep the server-rendered view on failure */ });
    }

    function loadPrograms(faculty, keepSelection) {
        if (!programSel) return;
        fetch(programsUrl + (faculty ? '?faculty=' + encodeURIComponent(faculty) : ''),
              { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var current = keepSelection ? programSel.value : '';
                var html = '<option value="">Semua Program Studi</option>';
                (data.study_programs || []).forEach(function (p) {
                    html += '<option value="' + p.value + '">' + p.label + '</option>';
                });
                programSel.innerHTML = html;
                if (current) programSel.value = current;
            })
            .catch(function () { /* leave the server-rendered list in place */ });
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        load();
    });

    if (facultySel) {
        // Dependent filter: narrowing the faculty narrows the program list.
        facultySel.addEventListener('change', function () {
            loadPrograms(facultySel.value, false);
        });
    }

    if (resetBtn) {
        resetBtn.addEventListener('click', function () {
            form.reset();
            if (facultySel) facultySel.value = '';
            loadPrograms('', false);
            load();
        });
    }

    var inline = document.getElementById('regm-chart-data');
    if (inline) {
        var initial = {};
        try { initial = JSON.parse(inline.textContent || '{}'); } catch (e) { initial = {}; }
        renderChart(initial);
    }

    window.addEventListener('resize', function () { if (chart) chart.resize(); });
})();
