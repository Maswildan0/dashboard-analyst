# Dashboard Analyst

Django 6 application (migrated from Laravel 13). No database; the dashboard is
powered by a deterministic mock dataset.

## Setup

```sh
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python manage.py runserver
```

## Conventions

- **Views** live in `dashboard/views.py`; the mock dataset in `dashboard/data.py`.
- Templates in `templates/` (Django template language; `{# #}` comments only —
  the include parser does not strip comments, keep them out of `components/`).
- RNG seed logic (`dashboard/views.py::_build_payload`) must stay byte-identical
  to the original PHP crc32+LCG so dashboard numbers match the Laravel version.
- Custom template filters/tags: `dashboard/templatetags/dashboard_filters.py`
  (`intcomma`, `fill_pct`, `index`, `sort_link`, `page_link`).
- Assets are prebuilt (`public/build/`) and served under `/build/`; rebuild via
  `npm run build` (needs `package.json` restored from git history if removed).

## Tests

```sh
python manage.py check
```
