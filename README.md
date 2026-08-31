# Dashboard Analyst

Dashboard analisis realisasi proyek (Telkom) dengan halaman dashboard interaktif dan tabel Data Realisasi. Migrasi dari Laravel 13 → Django 6.

## Teknologi

- **Django 6.1** (Python 3.13) — backend, routing, template
- **Chart.js** + Tailwind CSS 4 (via Vite build) — frontend; asset statis sudah di-*build* di `public/build/`

## Menjalankan

```sh
python -m venv .venv
.venv\Scripts\activate        # Windows (PowerShell)
pip install -r requirements.txt

python manage.py runserver    # http://127.0.0.1:8000
```

Route:

| URL              | Fungsi                                              |
| ---------------- | --------------------------------------------------- |
| `/`              | Dashboard (grafik + KPI)                            |
| `/dashboard/data`| JSON payload untuk filter dashboard                 |
| `/data`          | Tabel Data Realisasi (filter, sort, pagination)     |
| `/data/export`   | Ekspor CSV sesuai filter aktif                      |

## Struktur

```
dashboard/
  data.py       # dataset mock 32 proyek × 12 bulan (1:1 dari versi Laravel)
  views.py      # logika filter, payload, tabel, export
  urls.py       # routing
templates/      # layout, dashboard, realisasi, komponen multi-select
public/         # asset statis + hasil build Vite
```

Data sepenuhnya deterministik (seed CRC32 + LCG) — tidak ada database; seluruhnya mock sesuai controller Laravel asli.

## Rebuild asset frontend

Jika ingin mengubah CSS/JS:

```sh
npm install
npm run build      # menulis public/build/
```

## Catatan migrasi

- Kontrak URL & query string dipertahankan 1:1 (termasuk `tahun[0]=2025` dari link pagination Laravel, dan `tahun[]` dari form).
- Filter divalidasi dengan allowlist yang sama; nilai tidak dikenal fallback ke default.
- RNG seed `crc32` + LCG PHP direplikasi agar payload dashboard identik dengan versi Laravel.
