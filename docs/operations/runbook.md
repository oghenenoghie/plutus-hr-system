# Operations runbook

How to deploy, configure, back up and recover Plutus, and how to run the
inventory module day to day. Background and decisions are in
`docs/architecture/inventory-integration.md`; this file is the procedure.

| Piece | Where it runs | Deployed from |
|---|---|---|
| API (`plutus-hr-system`) | Railway service `plutus-api` | `main`. `railway.json` runs `alembic upgrade head` as the pre-deploy command, then uvicorn. Health check: `GET /api/v1/health`. |
| Database | Railway Postgres | (managed) |
| Web app (`plutus-hr-system-frontend`) | Two Vercel projects | `main` |
| Desktop app (`desktop_plutus_hr-*`) | The user's computer: Electron, the bundled API and an embedded Postgres | The `Build desktop app` workflow (manually, or on a `desktop-v*` tag) |

Never run tests, seed scripts or the end-to-end suite against the production
database. They create organisations and post stock.

---

## 1. Database roles

Row-level security (RLS) keeps each organisation's rows away from every
other organisation. **It doesn't apply to a superuser, a role with
`BYPASSRLS`, or the owner of the tables.** So the API must connect as an
ordinary role, and only migrations run as the owner.

| Setting | Holds |
|---|---|
| `MIGRATION_DATABASE_URL` | The owner's connection: the role that created the tables. Migrations run as it. If unset, migrations use `DATABASE_URL`. |
| `DATABASE_URL` | The API's connection, as the ordinary role. |
| `APP_DATABASE_ROLE` | That ordinary role's name. When set, every migration run grants it access to new tables (`grant_app_role` in `alembic/env.py`). |
| `REQUIRE_RLS_ENFORCED` | `true`: the API refuses to start unless RLS binds its connection. Default `false`: it starts and logs a warning. |

At startup the API checks its own connection (`app/core/db_roles.py`). If RLS doesn't
bind it, the log shows:

> the database role '…' is a superuser, has BYPASSRLS or owns the tables, so row-level security is not enforced; …

### 1.1 Moving production to an ordinary role (one time)

1. **Back up** (§4.1).
2. Create the role with a fresh random password (for example `openssl rand -hex 24`).
   While `DATABASE_URL` is still the owner's connection, run:
   ```bash
   APP_DATABASE_PASSWORD='<password>' \
     railway run --service plutus-api -- uv run python -m scripts.provision_app_role
   ```
   It creates the role, or resets it if it exists: `LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`.
   It grants read and write on every table and sequence, and the same on future ones. It denies `alembic_version`.
   It then checks that RLS binds the new role.
   It never prints the password. It's safe to run again.
3. In the Railway variables of `plutus-api`, set:
   - `MIGRATION_DATABASE_URL`: the **current** `DATABASE_URL` value (the owner);
   - `APP_DATABASE_ROLE=plutus_app`;
   - `DATABASE_URL`: the same host and database, as `plutus_app` with its password (the script prints the shape).
4. Deploy. In the deploy log, the migration step runs as the owner. In the API log, the warning above is **gone**.
5. Set `REQUIRE_RLS_ENFORCED=true` and deploy again. From now on, a misconfiguration stops the deploy instead of serving every organisation's rows.
6. Smoke-check: sign in, open a few pages, and post nothing.

**To roll back:** set `DATABASE_URL` back to the owner's connection, set
`REQUIRE_RLS_ENFORCED=false` and redeploy. The role can stay; it's harmless.

### 1.2 Desktop

The embedded cluster's own user `plutus` is a superuser. On every launch,
`app/desktop_main.py`:
1. migrates as `plutus`;
2. provisions `plutus_app` with the password Electron keeps in `pg-app-password.txt`;
3. serves as `plutus_app` with `REQUIRE_RLS_ENFORCED=true`.

An Electron shell older than Phase 5 passes no app password. Its API serves as `plutus` and logs the warning.

---

## 2. Releasing

1. CI is green on the PR: ruff, mypy, migration to head on a fresh database, and pytest. The frontend's `tsc`, lint and build are clean.
2. If the release has a migration:
   - read it again: forward-only, and nothing edits a migration that's already deployed;
   - take a backup (§4.1).
3. **Backend first.** Merging to `main` deploys `plutus-api`, and its pre-deploy step migrates. Migrations are additive, so the web app already live keeps working against the new API.
4. Check `GET /api/v1/health` and the API log: no startup error, and no RLS warning.
5. **Then the frontend.** Merging to `main` deploys both Vercel projects.
6. **Desktop.** Port every backend change to `desktop_plutus_hr-backend`, and every `src/` change to `desktop_plutus_hr-frontend`; `app/`, `alembic/` and `src/` stay identical to cloud. Push a `desktop-v<version>` tag to build the installers. The Windows job installs the app, launches it, and waits for both the API and the web server to answer.

### 2.1 If a deploy fails

- **The pre-deploy migration failed.** The new code never starts. Confirm in Railway that the previous deployment is still the active one. Alembic runs each upgrade in a transaction and Postgres DDL is transactional, so the failed revision left nothing behind. Fix forward with a new revision, and never edit the failed one once it's on `main`.
- **The API won't start with `RlsBypassError`.** `DATABASE_URL` points at the owner or a superuser. Correct it (§1.1). Don't clear `REQUIRE_RLS_ENFORCED` unless you are deliberately rolling back.
- **The API is up but behaving wrongly.** Redeploy the previous deployment from Railway. If the bad release migrated, the schema is ahead of the code, which is fine for additive migrations. Otherwise restore (§4.2).

---

## 3. Migrations

- **Forward-only.** A downgrade is for development, and for a deploy that hasn't written data yet. Once documents have posted, recovery is a restore, not a downgrade.
- **Never edit a migration that has been deployed.** Write a new revision.
- **Never drop a production table or reset a shared database.**
- Migrations are tested upgrade → downgrade → upgrade on a fresh database before merging (`alembic check` reports only the known non-inventory index drift).
- `7f6106c58e40` (Phase 5) only adds indexes. It runs plain `CREATE INDEX`, which blocks writes to each table while that index builds: well under a second at current volumes. If a table has grown large by the time it runs, deploy it at a quiet hour.

---

## 4. Backups and recovery

### 4.1 Taking a backup (cloud)

Before every release that migrates, and at least daily (in addition to any backups Railway itself keeps):

```bash
pg_dump --format=custom --no-owner --no-privileges \
  --file="plutus-$(date +%Y%m%d-%H%M).dump" "postgresql://<owner>:<password>@<host>:<port>/<database>"
```

- Use the owner's connection (`MIGRATION_DATABASE_URL` without the `+psycopg`). A dump made as the ordinary role would hold only what RLS lets it see, which is nothing.
- Keep the dump off the database host, and keep at least the last seven.

### 4.2 Restoring (cloud)

Restore into a **new** database and switch to it. Never restore over the live one.

1. Create a new database on the server (or a new Railway Postgres).
2. `pg_restore --no-owner --no-privileges --dbname="<new owner URL>" plutus-….dump`
3. Run `uv run python -m scripts.provision_app_role` against it (§1.1, step 2) to recreate the grants.
4. Check it before switching: the row counts of `organisations`, `journal_entries` and `inventory_stock_movements` are as expected, and `GET /inventory/reconciliation` for a known organisation reconciles.
5. Point `MIGRATION_DATABASE_URL` and `DATABASE_URL` at the new database and redeploy.
6. Keep the old database until the restored one has run for a while.

### 4.3 Desktop

Everything is under the app's data folder:
- the database (`pgdata`);
- the secrets (`pg-password.txt`, `pg-app-password.txt`, `jwt-secret.txt`, `object-storage-secret.txt`).

| OS | Data folder |
|---|---|
| Windows | `%APPDATA%\plutus-hr-system-frontend` |
| macOS | `~/Library/Application Support/plutus-hr-system-frontend` |
| Linux | `~/.config/plutus-hr-system-frontend` |

- **Back up:** quit the app (all windows, and check the tray or Dock), then copy the whole folder.
- **Before installing a new version, back up first.** The new version migrates the database on its first launch.
- **To restore:** quit the app, replace the folder with the copy, then start the app.
- Copy the folder as a whole. The database only opens with the passwords stored next to it.

---

## 5. Inventory, day to day

### 5.1 Switching it on

Inventory is off per organisation until a manager switches it on: Inventory Settings → Switch on.
Switching it on seeds five accounts in the chart: `inventory`, `grni`, `inventory_consumption`, `inventory_adjustment` and `inventory_opening_balance`.
Then set up, in this order:
1. warehouses;
2. units and categories (a category can name the account its issues are charged to; otherwise `inventory_consumption`);
3. items;
4. opening stock, as opening-balance adjustments.

An organisation that held stock before inventory accounting existed starts it
once, with Inventory Settings → Accounting → Start (`POST /inventory/accounting/start`):
- it needs both `inventory.manage` and `accounting.manage`;
- it posts the stock held that day as one opening journal (Dr `inventory`, Cr `inventory_opening_balance`);
- **it is one-way.**

### 5.2 Reconciliation

The Inventory overview's Ledger reconciliation card (`GET /inventory/reconciliation`) compares:
- stock value with the GL `inventory` balance;
- unbilled receipts with the GL `grni` balance.

Both differences should be **zero**. Check at every month end, before setting the lock date.
A difference means something reached one side only. The usual cause is a manual journal, bill or expense coded to `inventory` or `grni`. Reverse it, and record the stock change with an inventory document instead.

Investigate before closing the month. Don't post a balancing journal to hide it.

### 5.3 Month end

1. Post every receipt, issue, transfer and adjustment dated in the month.
2. Run a stocktake for each warehouse that is due (§5.4).
3. Check the reconciliation is zero (§5.2). Download the valuation report as at the month end (Inventory Reports → Valuation, CSV or PDF) for the file.
4. Set the lock date to the last day of the month: Accounting Settings, or `PATCH /accounting-settings`. Nothing dated on or before it can post afterwards.

### 5.4 Stocktakes

1. Create one per warehouse (optionally one category), and **Start** it at the moment counting begins. Start takes the snapshot. Work can carry on: anything posted after the start is kept, because the count posts only the difference.
2. Count, and enter every line, using 0 for stock that isn't there. Add stock found that the snapshot didn't list.
3. Submit. Missing stock, and gains above the adjustment limit, go for approval.
4. Post. The variances post as adjustments, with one journal.

A wrong count can't be reversed: correct it with an adjustment.

### 5.5 Correcting mistakes

- **Posted documents, movements and journals are never deleted or edited.** The tables refuse it.
- A posted document is undone by **reversing** it from its page. A reversal is a new set of movements and a mirrored journal, so the trail shows both.
- A draft can be edited or deleted.
- A stock error with no document behind it is an **adjustment** (gain or loss, with a reason). Losses and large gains need approval.
- Never fix stock or ledger rows with SQL. The projections (balances, cost pools, lot balances) are maintained by the posting engine and must equal the movements.

---

## 6. Checks and tests

| What | Command |
|---|---|
| Backend lint, types | `uv run ruff check . && uv run ruff format --check . && uv run mypy app` |
| Backend tests | Run `uv run pytest` against a fresh, disposable database (`TEST_ADMIN_DATABASE_URL`, default `plutus_test` on localhost). It creates the role `plutus_app_test` and runs as it. |
| Migrations | `alembic upgrade head`, `alembic downgrade -1` and `alembic upgrade head`, on a scratch database |
| Frontend | `npm ci && npx tsc --noEmit && npm run lint && npm run build` |
| End to end | The frontend's `e2e/README.md`. Run it against a local API connected as an ordinary role, never production. |
| Installers | The `Build desktop app` workflow. The Windows job installs the app and checks that it starts. |
