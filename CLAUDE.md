# Dashboard Analyst — Agent Guidelines

Django 6 application migrated from Laravel 13. PHP/Laravel tooling is gone;
do not run `composer`/`artisan`/`php`.

## Stack

- Django 6.1 (Python 3.13), no database — deterministic mock dataset.
- Frontend: Chart.js + Tailwind 4, prebuilt by Vite into `public/build/`.

## Run

```sh
python manage.py runserver      # http://127.0.0.1:8000
python manage.py check          # system checks
```

## Conventions

- Business logic in `dashboard/views.py` (filters, payload, table, export);
  dataset in `dashboard/data.py`.
- Templates (Django DTL) in `templates/`. Keep `{# #}` comments out of
  `templates/components/` — the include parser leaks them into output.
- `_build_payload` replicates the original PHP crc32+LCG seeding; keep it
  byte-identical (dashboard numbers are a parity contract with the old app).
- Template helpers live in `dashboard/templatetags/dashboard_filters.py`.
- Query-string contract preserved from Laravel: `tahun[0]=...` (links) and
  `tahun[]` (forms) are both accepted; see `_multivalue`.

## Editing frontend

`npm run build` writes `public/build/` (needs `package.json` + `node_modules`).
