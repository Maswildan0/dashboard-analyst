# Financial Analyst Dashboard

Aplikasi monitoring & analisis kinerja keuangan organisasi/universitas — Revenue, Expense, SHU, Operating Ratio, SHU Margin, dan komposisi revenue (Tuition Fee / NTF Project / NTF Research). Dibangun dengan Django, ECharts, dan template Django.

> Milestone 1: landing page Financial Performance Overview lengkap (KPI cards, profitability, revenue composition, monthly trend, analyst insights, filter global, unit tests).

## Teknologi

- Python 3.13 + Django 6.1
- SQLite (development) / PostgreSQL (production via env)
- Apache ECharts (trend chart)
- Bootstrap Icons + CSS kustom corporate

## Instalasi

```sh
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_financial_data   # sample data 2025-2026 Jan-Agu, 4 campus
python manage.py createsuperuser
python manage.py runserver
```

Buka `http://127.0.0.1:8000/financial/`.

## Struktur

```
finance/
  models.py            # master data + fact tables (DecimalField, index)
  views.py             # FinancialDashboardView + context builder
  selectors/           # optimized aggregate queries
  services/
    financial_metrics.py  # SEMUA formula KPI (achievement, YoY, ratio, margin, komposisi)
    formatters.py         # Rp Miliar / persen Indonesia
    insights.py           # rule-based analyst insights
  management/commands/seed_financial_data.py
  templates/finance/      # dashboard + komponen reusable
  static/finance/         # dashboard.css + dashboard.js (sidebar, chart, tooltip)
  tests/                  # 32 unit tests (formula + view)
```

## Aturan bisnis penting

- **YoY selalu bulan berjalan vs bulan sama tahun sebelumnya** (#53) — bukan YTD.
- Operating Ratio achievement: **lower is better** (Target/Actual).
- SHU Margin achievement: **higher is better** (Actual/Target).
- Komposisi revenue divalidasi: TF + NTF Project + NTF Research ≈ Total Revenue.
- Tidak ada KPI kalkulasi yang disimpan — semua dihitung service layer dari data dasar (#30).
- Zero-denominator → `None` → tampil "N/A" (tidak pernah infinity).

## Admin

Model terdaftar di Django admin: Campus, OrganizationUnit, FinancialPeriod, RevenueCategory, FinancialSummary, RevenueTransactionSummary, KpiTarget, FinancialDataAuditLog.

## Test

```sh
python manage.py test finance
```

## Postgres production

Set env: `DB_ENGINE=postgres DB_NAME DB_USER DB_PASSWORD DB_HOST DB_PORT`.
