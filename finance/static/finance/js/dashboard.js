/* Financial Analyst Dashboard UI interactions (sidebar, tooltip, chart). */
(function () {
    'use strict';

    // Sidebar collapse (#3): hidden by default; toggle slides it in and out.
    const toggle = document.querySelector('.sidebar-toggle');
    const sidebar = document.getElementById('app-sidebar');
    if (toggle && sidebar) {
        toggle.addEventListener('click', () => {
            const open = sidebar.classList.toggle('open');
            document.body.classList.toggle('sidebar-active', open);
        });
    }

    // Trend chart (Apache ECharts, #20)
    const trendEl = document.getElementById('trend-chart');
    const trendDataEl = document.getElementById('trend-data');
    if (trendEl && trendDataEl && window.echarts) {
        let data = {};
        try { data = JSON.parse(trendDataEl.textContent || '{}'); } catch (e) { /* keep {} */ }
        const chart = echarts.init(trendEl);
        const series = {
            revenue: { name: 'Revenue', type: 'line', data: data.revenue || [], smooth: true, symbolSize: 6, lineStyle: { width: 3, color: '#C8102E' }, itemStyle: { color: '#C8102E' } },
            expense: { name: 'Expense', type: 'line', data: data.expense || [], smooth: true, symbolSize: 6, lineStyle: { width: 3, color: '#6B7280' }, itemStyle: { color: '#6B7280' } },
            shu: { name: 'SHU', type: 'line', data: data.shu || [], smooth: true, symbolSize: 6, lineStyle: { width: 3, color: '#8B0D24' }, itemStyle: { color: '#8B0D24' } },
        };
        const active = { revenue: true, expense: true, shu: true };

        function render() {
            chart.setOption({
                tooltip: {
                    trigger: 'axis',
                    formatter: (params) => {
                        let html = `<b>${params[0].axisValue}</b>`;
                        params.forEach(p => { html += `<br/>${p.seriesName}: Rp ${p.value.toLocaleString('id-ID')} M`; });
                        return html;
                    },
                },
                legend: { show: false },
                grid: { left: 60, right: 20, top: 30, bottom: 40 },
                xAxis: { type: 'category', data: data.months || [], boundaryGap: false, axisLine: { lineStyle: { color: '#E5E7EB' } }, axisLabel: { color: '#6B7280' } },
                yAxis: {
                    type: 'value', name: 'Rp Miliar', nameTextStyle: { color: '#9CA3AF' },
                    splitLine: { lineStyle: { color: '#F0F1F3' } }, axisLabel: { color: '#6B7280' },
                },
                series: Object.keys(active).filter(k => active[k]).map(k => series[k]),
            });
        }

        document.querySelectorAll('.trend-toggle').forEach((btn) => {
            btn.addEventListener('click', () => {
                const key = btn.dataset.series;
                active[key] = !active[key];
                btn.classList.toggle('active', active[key]);
                render();
            });
        });

        render();
        window.addEventListener('resize', () => chart.resize());
    }
})();
