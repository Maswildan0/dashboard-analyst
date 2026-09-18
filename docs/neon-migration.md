# MySQL → Neon: audit and migration gate

Status: **INCOMPLETE — access required; no source data migrated or production cutover performed.**

Audited repository: `Maswildan0/dashboard-analyst`, main commit
`8ea9d533b8b2b608d1ee5dd56f1b91dfa0e7d327`. Audit date: 2026-09-08.
This checkout is separate from `C:\HDD\code\dashboard analyst`. Local Windows
changes and its active database have not been inspected. Do not assume the
GitHub schema matches uncommitted local changes.

## Evidence and results

| Item | Status | Evidence / remaining work |
|---|---|---|
| Source database | WARNING | User identifies MySQL `financial_dashboard`; no connection/credentials available in this workspace. |
| Target database | WARNING | User identifies Neon via Vercel project `dashboard`; resource/branch not yet verified. |
| Neon connection | FAIL | No `DATABASE_URL` in workspace. Vercel team listing returned empty, project lookup in supplied scope returned 403, CLI reports logged out. |
| Django engine | PASS / WARNING | URL-based PostgreSQL configuration prepared; local tests use isolated SQLite, not the real source or Neon. Original checkout defaults to SQLite unless DB_ENGINE is set. |
| Tables migrated | WARNING | None. Code defines 21 finance models and 3 finance migrations. Actual source tables not yet counted. |
| Source/target counts | WARNING | Not measured. Read-only baseline command prepared. |
| Financial reconciliation | WARNING | Not run against real databases. Comparison detects a one-cent difference without float conversion. |
| FK integrity | WARNING | Real source/target not inspected; audit enumerates constraints and counts orphan relationships. |
| Business validation | WARNING | Existing code has discrepancies listed below; no automatic data corrections made. |
| Django check | PASS | `python manage.py check`; `makemigrations --check --dry-run` reports no changes. |
| Preview deployment | PASS / FAIL | Git integration built commit `ef4e8be` successfully. Runtime probes on `/`, `/dashboard/`, `/dashboard/revenue/` each returned HTTP 500. |
| Production deployment | WARNING | Not changed. Must wait for real backup, reconciliation and Preview validation. |
| Dashboard smoke test | FAIL | Three Preview routes return HTTP 500. Runtime log access and protected fetch are denied by Vercel (403); cause unconfirmed. Production not probed or changed. |
| Rollback | PASS / WARNING | Plan below; MySQL not accessed or modified. Live rollback cannot be rehearsed without access. |
| Other issues | WARNING | Linux MySQL driver build needs system development libraries. Windows workstation requires a compatible mysqlclient wheel/build. |

Local test environment: Python 3.13.14, Django 6.1.1, psycopg 3.3.5.
`python manage.py test finance --noinput`: **70 tests passed** (58 existing + 12
new tests). Temporary test fixtures are isolated and are never source/target
replacement data. SQLite tests do not prove MySQL/PostgreSQL decimal or DDL
compatibility. No new data migration was generated.

Preview checked after opening draft PR #1:
https://dashboard-git-migration-neon-controlled-preparation-maswildan0.vercel.app

Vercel's exact access error identifies scope `maswildan0` and requires
re-authentication to that scope. Both the project slug and the project/team IDs
reported by the Vercel GitHub bot were checked and denied. Build success is not
runtime success. Missing `DJANGO_SECRET_KEY`, missing/incorrect database envs,
or another initialization issue are possibilities, not confirmed diagnoses.

## Changes prepared

- Removed startup `migrate` and `seed_financial_data` from `FinanceConfig.ready`.
  Previously even an audit/check could create schema and dummy rows.
- `DATABASE_URL` now wins over legacy `DB_ENGINE`; PostgreSQL URL requires TLS,
  uses `CONN_MAX_AGE=0`, and disables server-side cursors for transaction pooling.
- Vercel fails closed if database configuration is missing. No `/tmp` SQLite fallback.
- Added PostgreSQL driver, URL parser, and explicit local dotenv loading.
- Kept legacy MySQL configuration and its MariaDB backend. Its driver is an
  explicit migration/fallback dependency in `requirements-migration.txt`.
- Pinned Python selection to 3.13. Vercel requires an environment-provided
  `DJANGO_SECRET_KEY` and defaults to debug disabled.
- Removed the legacy custom 15 MB Python bundle cap to allow the PostgreSQL
  binary driver; Vercel platform limits still apply. Actual build is unverified.
- Added read-only audit, exact comparison and a TLS connection probe. Secrets
  and original database rows are never printed or included in audit reports.
  Reports contain schema, counts, sums and hashes, so still treat them as
  internal financial records.

## Existing code findings that require a decision after source inspection

1. `Project` has a PP foreign key but no `revenue_account` foreign key. The
   schema does not enforce “one project = one account”. The project service
   still contains a `Multi Akun` label. The audit flags cross-account mappings
   as `PROJECT_ACCOUNT_MISMATCH`; it never merges or changes them.
2. `project_lifetime()` currently sums all mapped periods. Some other helper
   paths filter to the selected date, but consistent selected-period behavior
   is not yet verified for every UI path.
3. `org_pp_performance()` applies `ctx.filter_ledger()`, which narrows to the
   selected month, and sorts organization names alphabetically. Its current
   implementation does not satisfy the requested Actual YTD DESC ranking.
4. Closing snapshots skip GL rows without a normalized revenue account.
   Project closing calculations also contain an unrestricted lifetime sum.
   Frozen values must not be recomputed automatically to hide this difference.
5. MySQL does not enforce the conditional unique constraint on nonempty GL
   source transaction IDs; PostgreSQL does. Source duplicates must be audited
   before any insert. No deletion/deduplication is authorized implicitly.
6. MySQL's existing backend relaxes MariaDB version requirements for XAMPP.
   Keep the source unchanged and validate its actual schema/types before import.

## Next action on the Windows computer

This step is needed because only that computer currently has the local source
database and its configuration. It performs read-only probes, not migration.
Do not paste any `.env`, token, connection URL or password into chat.

Open PowerShell and create a separate checkout so local edits remain intact:

```powershell
Set-Location 'C:\HDD\code\dashboard analyst'
git status --short
git fetch origin migration/neon-controlled-preparation
git worktree add '..\dashboard-neon-migration' origin/migration/neon-controlled-preparation
Set-Location '..\dashboard-neon-migration'
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-migration.txt
```

If the worktree already exists, use that folder; do not delete it. If Python
3.13 is not installed, use an existing compatible Python 3.13/3.14 interpreter.
Stop on an installation error and share only the non-secret error message.

Log in to the existing Vercel account if needed, then link **the existing**
project. Do not create a new project:

```powershell
npx vercel login
npx vercel link --project dashboard
npx vercel env pull .env.preview.local --environment=preview
```

Select the account/team that owns `dashboard` when prompted. Expected result:
the folder is linked to the existing project and `.env.preview.local` is saved.
Do not open or print this file. Development integration is not required.

If MySQL uses an existing environment file, select that exact file in the
command below (replace `.env` only if the actual file has a different name):

```powershell
$env:SOURCE_DB_NAME = 'financial_dashboard'
.\.venv\Scripts\python.exe scripts\run_migration_preflight.py --source-env-file 'C:\HDD\code\dashboard analyst\.env' --target-env-file .env.preview.local
```

The source file must contain `DB_ENGINE=mysql` plus the existing `DB_*` values,
or `SOURCE_DB_*` values. Credentials are read inside Python, never echoed.
If there is no source `.env` and the existing source uses the repository's
XAMPP defaults (127.0.0.1:3306, root, empty password), omit `--source-env-file`.
For a non-default source, use its existing local configuration; do not guess a
password. Prefer a source account with SELECT/metadata-only privileges.

Expected output includes:

```text
Vendor: mysql; read-only: True; status: PASS
Source audit = PASS
DATABASE_URL exists = True
connection.vendor = postgresql
Database connection = OK
SSL = True
No schema migration, backup, import or deployment performed.
```

`WARNING` is also a useful result: the timestamped source audit file records
the precise findings. Send the non-secret terminal summary and, if permitted,
the audit JSON from `.migration-artifacts`. Never send `.env` or a database
backup through chat. Do not run `migrate` on the source.

To give the connected Vercel tools access, reconnect the Vercel app using the
same account/team that owns `dashboard`. CLI login on Windows authorizes that
computer only; it does not authorize this separate cloud workspace.

The current Preview HTTP 500 needs runtime logs. In Vercel, open the existing
`dashboard` project → Deployments → the deployment for
`migration/neon-controlled-preparation` → Runtime Logs (or the project's Logs
tab), then reload `/dashboard/revenue/`. Share only the error name and message,
with connection URLs, usernames and passwords removed, if app re-authentication
cannot be completed. Check variable **names/presence** in Preview for
`DATABASE_URL` and `DJANGO_SECRET_KEY`; never share their values. This is an
access/configuration gate, not permission to cut over Production.

## Gated continuation — not yet executed

1. Compare the Windows checkout revision/models against this audit, inspect all
   source columns, PK/FK/unique/index definitions, storage engines and row counts.
   The audit uses a consistent read-only snapshot; non-InnoDB tables block a
   consistency claim. No concurrent DDL during source audit/backup.
2. Quiesce application/sync writes for the final migration window. Keep MySQL
   online and read-only to the migration process. A consistent snapshot alone
   cannot capture writes made after that snapshot.
3. Create and verify a source-native schema+data backup with a protected local
   credential file (never password flags). Record file size and SHA-256 and
   perform a restore rehearsal in a disposable database. Store it outside git.
   The audit JSON is **not** a backup.
4. Verify the intended Neon Preview branch. Determine whether Preview and
   Production URLs point to distinct databases before touching either.
5. Implement the reusable importer against the verified source schema, using
   Django migrations for the target schema, explicit PK/FK-preserving inserts,
   exact Decimal/NULL/date/boolean handling and a target transaction. Do not
   disable FK constraints. Handle organization self-relations and auth M2M
   tables. Reconcile existing target contenttypes/permissions without deleting
   data or guessing ID mappings. Refuse nonempty/conflicting targets.
6. Audit `migrate --plan` against the direct Neon connection and apply only the
   verified plan. Source migration history is audit metadata; target Django
   migration history must reflect schema actually applied there.
7. Import, reset and verify sequences, run target read-only audit, and compare
   every row count, row-value hash and Decimal aggregate. Require zero diffs:

   ```powershell
   .\.venv\Scripts\python.exe manage.py audit_migration_database --database default --expect-vendor postgresql --output .migration-artifacts\target-audit.json --settings dashboard.migration_settings
   .\.venv\Scripts\python.exe scripts\compare_migration_audits.py .migration-artifacts\source-audit.json .migration-artifacts\target-audit.json
   ```

   Use the actual timestamped source filename. Audit settings require source
   variables and target environment loaded in that process. The scripts reject
   existing report files, missing tables/hashes, orphan relationships and any
   financial mismatch. Engine-specific schema types/index names are audited
   separately; matching hashes do not prove equivalent constraints.
8. Validate August 2026 on both engines: Actual YTD, RKA YTD, variance,
   achievement, category composition, each project's selected-month/lifetime
   values and organization/PP ranking. Flag source business-rule failures
   separately from migration differences. Do not change amounts to obtain PASS.
9. Deploy Preview, verify the actual DB vendor and logs, and smoke-test `/`,
   `/dashboard/`, `/dashboard/revenue/`, TF, NTF Research, NTF Project, expanded
   GL history, filters, RKA, composition and ranking. The original `/dashboard/`
   still uses mock data; HTTP 200 on that route alone does not prove Neon is used.
10. Reconcile final source state during the agreed write pause, then cut over
    Production only after all gates pass. If Preview/Production databases differ,
    Production needs its own verified import and reconciliation. No dummy seed.

## Rollback

- Before cutover, record the current production deployment ID and protected
  database configuration. Keep the verified MySQL backup and running source.
- If no writes occurred after cutover, restore the known-good production
  deployment/configuration. Remove `DATABASE_URL` (and direct URL where used)
  from that deployment's runtime selection and restore `DB_ENGINE=mysql` and
  the original `DB_*` variables through Vercel's secure environment interface.
  Ensure the rollback runtime includes mysqlclient and can reach that MySQL
  host. A local `127.0.0.1` MySQL instance is not reachable from Vercel.
- Changing project environment variables requires a new deployment; it does
  not retroactively change an already-built deployment. Verify DB vendor and
  run the same smoke tests after rollback.
- If PostgreSQL accepted new writes, freeze writes first and reconcile those
  changes back to MySQL in a separate reviewed process. Blind rollback would
  lose post-cutover transactions. Do not delete either database.

## Technical references

- [Django PostgreSQL and transaction pooling](https://docs.djangoproject.com/en/6.1/ref/databases/)
- [Vercel Python version selection](https://vercel.com/docs/functions/runtimes/python/python-version)
