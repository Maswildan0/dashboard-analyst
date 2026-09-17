# Financial Analyst Dashboard

Aplikasi monitoring & analisis kinerja keuangan organisasi/universitas — Revenue, Expense, SHU, Operating Ratio, SHU Margin, dan komposisi revenue (Tuition Fee / NTF Project / NTF Research). Dibangun dengan Django, ECharts, dan template Django.

> Milestone 1: landing page Financial Performance Overview lengkap (KPI cards, profitability, revenue composition, monthly trend, analyst insights, filter global, unit tests).

## Teknologi

- MariaDB/MySQL (XAMPP `financial_dashboard`, default) — SQLite hanya utk Vercel cold start
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

Database initialization is explicit. Startup no longer runs migrations or
generates sample data. Do **not** run seed commands against an existing source
or a Neon migration target. For the MySQL-to-Neon work, read
[the migration audit and access steps](docs/neon-migration.md).

The optional sample-data command above is for a disposable local demo only.

Buka `http://127.0.0.1:8000/financial/`.

## Struktur

```
finance/
  models.py            # master data + fact tables (DecimalField, index)
  views.py             # Financial Performance Overview: filter + display context
  selectors/           # master-data + period queries
  services/
    financial_overview.py # SUMBER KANONIK halaman: GL/snapshot -> Revenue, RKA, KPI target
    financial_metrics.py  # SEMUA formula KPI (achievement, YoY, ratio, margin, komposisi)
    formatters.py         # Rp Miliar / persen Indonesia
    insights.py           # rule-based analyst insights (section sedang nonaktif)
  management/commands/
    reconcile_financial_overview.py  # cetak angka DB vs halaman utk rekonsiliasi
    seed_financial_data.py           # sample data (legacy summary tables)
  templates/finance/      # dashboard + komponen reusable
  static/finance/         # dashboard.css + dashboard.js (sidebar, chart, tooltip)
  tests/                  # unit test formula + kontrak halaman (lihat test_financial_overview.py)
```

## Sumber data Financial Performance Overview

Satu sumber kanonik per metrik (`finance/services/financial_overview.py`);
kartu, rasio, dan chart membaca payload yang sama sehingga tidak bisa
saling bertentangan.

| Metrik | Sumber | Catatan |
|---|---|---|
| Revenue Actual YTD | `RevenueMonthlySnapshot` (periode CLOSED, beku) + `RevenueLedger` credit−debit (periode OPEN) | skope `period → pp → OrganizationUnit → Campus`; GL tanpa mapping tetap dihitung |
| Revenue RKA YTD | `RevenueBudget` + `RevenueBudgetMonthly` pada `RkaVersion` aktif | di-phase per bulan, dijumlah Jan..bulan terpilih (bukan RKA annual penuh) |
| Revenue Achievement | Revenue Actual YTD / RKA YTD | RKA 0 → N/A |
| Revenue YoY | YTD tahun berjalan vs YTD tahun-1 (window sama) | |
| KPI Target (OR, SHU Margin) | `finance_kpitarget` | target per-campus dipakai lebih dulu, lalu target global |
| Expense / SHU / Operating Ratio / SHU Margin | **tidak tersedia** | belum ada sumber expense otoritatif; ditampilkan N/A + log `DATA_NOT_AVAILABLE`, tidak pernah diisi angka dummy |

Semua hasil YTD (Januari..bulan terpilih). Chart trend memakai **actual
bulanan** (bukan kumulatif) Jan..bulan terpilih. Filter Tahun/Bulan/Campus/
Organisasi memengaruhi seluruh kartu, rasio, dan chart; Organisation yang
bukan anggota Campus terpilih otomatis dibersihkan (cascading).

Rekonsiliasi development:

```sh
python manage.py reconcile_financial_overview --year 2026 --month 8 --campus BDG
```

## Aturan bisnis penting

- **YoY membandingkan window yang sama** — halaman ini memakai YTD vs YTD
  tahun sebelumnya (bukan bulan vs bulan).
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

`DATABASE_URL` takes precedence and requires PostgreSQL with SSL. Vercel cannot
fall back to temporary SQLite. Configure `DJANGO_SECRET_KEY` on Vercel; never
commit or paste its value. Python 3.13 is selected in `.python-version`.

Legacy `DB_ENGINE=postgres` / `DB_ENGINE=mysql` with `DB_NAME DB_USER DB_PASSWORD
DB_HOST DB_PORT` remains available when `DATABASE_URL` is absent. MySQL also
requires `pip install -r requirements-migration.txt` on that workstation/runtime.

To load one local file explicitly, set `DJANGO_ENV_FILE` to its path. Process
environment variables take precedence. For a migration audit, prefer
`scripts/run_migration_preflight.py`, which selects the source and target files
separately and never prints connection strings.
