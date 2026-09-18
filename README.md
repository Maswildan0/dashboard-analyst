# Financial Analyst Dashboard

Aplikasi monitoring & analisis kinerja keuangan organisasi/universitas — Revenue, Expense, SHU, Operating Ratio, SHU Margin, dan komposisi revenue (Tuition Fee / NTF Project / NTF Research). Dibangun dengan Django, ECharts, dan template Django.

> Milestone 1: landing page Financial Performance Overview lengkap (KPI cards, profitability, revenue composition, monthly trend, analyst insights, filter global, unit tests).

## Teknologi

- PostgreSQL / Neon (`DATABASE_URL`) untuk production dan pengembangan
- MariaDB/MySQL XAMPP `financial_dashboard` sebagai default **lokal** (management
  command saja); SQLite `/tmp` hanya untuk cold start Vercel tanpa DATABASE_URL
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

## Registrasi Mahasiswa

Halaman `/dashboard/registrasi-mahasiswa/` menganalisis kuota, registrasi, dan
tarif BPP per tahun (2019–2026) dengan filter Fakultas dan Program Studi
(dropdown Prodi mengikuti Fakultas yang dipilih).

Sumber data: `finance/data/student_registration.json`, hasil ekstraksi sheet
**Data Long** (821 baris, 115 program studi, 10 fakultas/kampus). Belum ada
tabel database untuk data ini, jadi file tersebut adalah sumbernya untuk saat
ini; seluruh pembacaan terpusat di
`finance/services/student_registration_service.py`, sehingga tahap berikutnya
(upload Excel) cukup mengganti loader tanpa mengubah view atau template.

Aturan agregasi:

| Ukuran | Aturan |
|---|---|
| Kuota | **SUM** antar program studi |
| Registrasi | **SUM** antar program studi |
| Tarif BPP | **AVERAGE** dari tarif non-null — **tidak pernah dijumlah** |
| Capaian | Registrasi / Kuota × 100; Kuota 0 → tampil `-` |
| Selisih | Registrasi − Kuota |

Tarif kosong tetap `null` (bukan 0). Kuota/registrasi kosong dianggap 0. Baris
yang ketiganya kosong dibuang. Tarif `0` yang tertulis eksplisit di workbook
tetap ikut dirata-ratakan, jadi rata-rata 2019 tampak rendah karena 23 dari 82
program memang bertarif 0 pada tahun itu.

Endpoint: `/dashboard/registrasi-mahasiswa/data/` (JSON agregat) dan
`/dashboard/registrasi-mahasiswa/program-studi/?faculty=...` (dropdown
dependent). Halaman ini privat seperti halaman lain (lihat `finance/middleware.py`).

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

## Database

`DATABASE_URL` takes precedence and requires PostgreSQL with SSL. Vercel cannot
fall back to temporary SQLite. Configure `DJANGO_SECRET_KEY` on Vercel; never
commit or paste its value. Python 3.13 is selected in `.python-version`.

Legacy `DB_ENGINE=postgres` / `DB_ENGINE=mysql` with `DB_NAME DB_USER DB_PASSWORD
DB_HOST DB_PORT` remains available when `DATABASE_URL` is absent. MySQL also
requires `pip install -r requirements-migration.txt` on that workstation/runtime.

Vercel installs `requirements.txt` and nothing else, so it stays PostgreSQL-only.
Keep it that way: `mysqlclient` has no Linux wheel, so listing it there makes the
deployment compile it against `libmariadb`, fail `pkg-config`, and abort.
`requirements-migration.txt` is the only file that may carry a MySQL driver, and
`ProductionRequirementsTests` fails the suite if one is added back.

To load one local file explicitly, set `DJANGO_ENV_FILE` to its path. Process
environment variables take precedence. For a migration audit, prefer
`scripts/run_migration_preflight.py`, which selects the source and target files
separately and never prints connection strings.
