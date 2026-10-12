# Inventory Integration — Architecture Discovery (Phase 0)

Status: **Phase 1 implemented.** The §12 defaults were approved on 2026-10-12, and Phase 1 (foundation) is built. §13 records what was built and how it differs from the proposals. §1–§11 are the original discovery report, kept as written.

Written against `plutus-hr-system` `main` @ `562458d` (2026-10-11) and `plutus-hr-system-frontend` `main` @ `50b45f1`, following `.claude/skills/plutus-inventory/SKILL.md`.

Every statement is tagged:

- **[V]** Verified by reading the code at the commits above. A file reference is given.
- **[A]** Assumption or inference. It still needs confirming.
- **[P]** Proposal. It needs approval before implementation.
- **[D]** Open business decision, listed in §12.

Companion document: [`ACCOUNTING_IMPLEMENTATION_AUDIT.md`](../../ACCOUNTING_IMPLEMENTATION_AUDIT.md) ("the audit"). The audit's open items (P1…P26) and assumptions (A1…A28) are referenced by number, not repeated.

---

## 0. Stack correction

The skill's wording assumes a Next.js + Supabase application. **This product does not use Supabase. [V]** The skill's terms map onto this codebase as follows:

| Skill says | This codebase actually has |
|---|---|
| Supabase Auth | Own JWT auth: `POST /api/v1/auth/login` issues an access/refresh pair, verified in `app/core/security.py` and `app/core/deps.py:get_current_claims` [V] |
| Supabase server client / service role | SQLAlchemy 2.0 sessions; `app/core/db.py:tenant_session` sets per-transaction GUCs [V] |
| RLS policies | Postgres RLS with `ENABLE` + `FORCE ROW LEVEL SECURITY`; policy `org_id = NULLIF(current_setting('app.current_org', true), '')::uuid` [V] (e.g. `alembic/versions/4f1c9a7e2b30_*.py:109-113`) |
| Server actions | FastAPI routers under `app/api/v1/*.py`, called by the client-rendered Next.js app over `fetch` [V] |
| Ordered SQL migrations | Alembic, single head (`4f1c9a7e2b30`), run with `alembic upgrade head` (Railway `preDeployCommand`; desktop `app/desktop_main.py` at startup) [V] |
| E2E test tool | **None configured** in the frontend (`package.json` scripts are `dev`, `build`, `start`, `lint` only) [V] |

The skill's requirements still apply in full. They are applied to this stack.

---

## 1. Application and package structure

### 1.1 Repositories [V]

| Repo | Role | Notes |
|---|---|---|
| `plutus-hr-system` | FastAPI backend (cloud) | Deployed to Railway service `plutus-api` from `main` |
| `plutus-hr-system-frontend` | Next.js 16 / React 19 / Tailwind v4 web app | Two Vercel projects deploy `main` |
| `desktop_plutus_hr-backend` | The same backend plus PyInstaller packaging | Must receive every backend change in the same Alembic order (audit A28) |
| `desktop_plutus_hr-frontend` | The same `src/` plus an Electron shell with embedded Postgres | `src/` kept byte-identical to the cloud frontend |
| `plutus-technologies-landing-page` | Marketing site | Out of scope |

**Implication [P]:** every inventory backend PR must be ported to `desktop_plutus_hr-backend`, and every frontend PR to `desktop_plutus_hr-frontend`.

### 1.2 Backend layout [V]

```
app/
  api/v1/      FastAPI routers (one module per resource; 65 modules)
  core/        config, db (tenant_session), deps (auth/roles), security (JWT), storage
  domain/      pure logic, no ORM/FastAPI: money.py, permissions.py, accounting/posting_rules.py, payroll/...
  compliance/  versioned statutory rule engine
  models/      SQLAlchemy models (one module per table family)
  schemas/     Pydantic v2 request/response models
  services/    transactional business logic; routers call these
  workers/     APScheduler jobs
alembic/versions/   migrations (ruff-excluded)
tests/{unit,integration,golden,property}
```

### 1.3 Tooling [V]

- **Package manager:** `uv` (`uv.lock` committed).
- **Lint and format:** `ruff` at line length 100.
- **Types:** `mypy --strict` on `app`.
- **Tests:** `pytest` and Hypothesis.
- **CI** (`.github/workflows/ci.yml`): ruff check, ruff format `--check`, mypy, `alembic upgrade head` on a fresh Postgres 16, then pytest.
- **Integration tests** run against a real Postgres through `DATABASE_URL`, using helpers in `tests/integration/api_helpers.py` (`create_org`, `create_account_with_membership`, `login_with_mfa`, `create_employee`, `create_department`, `create_and_lock_pay_run`).
- **Isolation between tests:** none. The suite expects a fresh database per run, and reusing one fails on unique emails. This was observed during the company-address work.

### 1.4 Frontend layout [V]

- **Routes:** `src/app/(app)/<route>/page.tsx` for the admin shell, `src/app/me` for self-service, plus `login` and `signup`.
- **Data fetching:** client-rendered; plain `fetch` through `src/lib/api/client.ts` (`apiFetch`, `downloadAuthenticatedFile`, `uploadFile`).
- **API layer:** typed endpoint objects in `src/lib/api/endpoints.ts`. `src/lib/types.ts` mirrors the Pydantic schemas by hand.
- **Navigation:** `src/lib/nav.ts`. Each `NavItem` has `href`, `label`, a union-typed `icon` and `roles: Role[]`. Groups are Overview, HR, Accounts (Payroll, Payables & Receivables, Financial Information) and Company Info.
- **UI primitives** (`src/components/ui`): avatar, badge, button, card, confirm-action-button, confirm-dialog, data-state, data-table, drawer, input (Input/Textarea/Label), kpi-tile, select, table, tabs, toast. Also `components/approval-history-panel.tsx` and `email-pdf-drawer.tsx`.
- **Formatting:** `src/lib/format.ts` formats naira in whole units for `en-NG`.
- **Mock mode:** `NEXT_PUBLIC_MOCK_MODE=1` serves `src/lib/api/mock-fixtures.ts`. Inventory pages need fixtures there or must degrade gracefully [A].

---

## 2. Authentication and tenant isolation

- **[V] Identity.** The JWT access token (15 min) and refresh token (7 days) carry `org_id`, `account_id` and `role`. The org always comes from the token, never from the request body.
- **[V] Database scoping.** `get_tenant_db` opens `tenant_session(org_id, account_id, role)`. That sets `app.current_org`, `app.current_account` and `app.current_role` with `set_config(..., true)`, so they are transaction-scoped. **Only `app.current_org` is read by any policy** (`app/core/db.py:system_session` docstring).
- **[V] Tables without RLS.** `memberships` and `accounts` are deliberately untenanted, read through `get_untenanted_session`.
- **[V] Signup.** It opens its own tenant session with a client-generated org id (`app/services/organisation.py`).
- **[V] Desktop bypasses RLS.** The embedded database runs as the bootstrap superuser `plutus` (audit §2.4, A24), and superusers bypass even `FORCE` RLS. Desktop tenant isolation therefore rests on the application layer only.
- **[P] Required for every inventory table:** `org_id NOT NULL` with an FK to `organisations`, `ENABLE` + `FORCE ROW LEVEL SECURITY`, and the standard `*_tenant_isolation` policy.
- **[P] Cross-tenant references are not blocked by RLS on insert.** RLS on a referenced table doesn't stop an FK pointing at another org's row. Every service that accepts a foreign id (item, warehouse, vendor, department, branch, account code) must load it through the tenant session and reject it if it isn't found. That is the pattern `_expense_account_or_raise` uses in `app/services/bills.py:15`.

---

## 3. Organisation, branch and warehouse models

| Model | Key fields | Notes |
|---|---|---|
| `Organisation` (`app/models/organisation.py`) | `name`, `rc_number`, `company_tin`, `address`, `default_pay_frequency`, `default_pfa`, `states_of_operation` [V] | |
| `Branch` (`app/models/branch.py`) | `org_id`, `name` (unique per org), `state`, `address`, `manager_id → employees` [V] | A physical site |
| `Department` (`app/models/department.py`) | `org_id`, `name`, `manager_id` [V] | Already the ledger's cost-centre dimension: `ledger_entries.department_id`, `PostingLine.department_id` |
| Warehouse / stock location | **none exists** [V] | |
| `FixedAsset` | `department_id`, `asset_tag`, cost, depreciation, `category`, `assigned_employee_id` [V] | Transfers move between **departments** (`fixed_asset_transfers.from/to_department_id`), not locations |

**[P]** Add `inventory_warehouses` with an optional `branch_id` FK to `branches`. A branch may hold several warehouses; a warehouse is not a branch.

---

## 4. Accounting transaction and journal-posting contracts

### 4.1 Ledger and journals [V]

**`ledger_entries`** (`app/models/ledger.py`)
- Append-only: the `forbid_update_delete()` trigger blocks updates and deletes.
- Each row is single-sided (enforced by CHECK constraints), with `BIGINT` minor-unit amounts.
- The `account` column holds the chart **slug** (`String(64)`).
- Optional dimensions: `pay_run_id`, `employee_id`, `department_id`.
- A deferred trigger, `check_ledger_entry_balance`, enforces that each `journal_entry_id` balances at commit.

**`journal_entries`** (`app/models/journal_entry.py`, migration `4f1c9a7e2b30`, added 2026-10-11)
- One header per balanced journal; its id is the lines' `journal_entry_id`.
- Fields:
  - `entry_date`: the accounting date.
  - `source_type`: the `journal_source_type` enum.
  - `source_id`, `source_event`, `reference`, `created_by`.
  - `reversal_of_id` and `reversal_reason`.
- Unique indexes make a business event postable only once (`(org_id, source_type, source_id, source_event)` where `source_id IS NOT NULL`) and a journal reversible only once (`reversal_of_id`).
- Append-only, with RLS.

**`app/services/posting.py`** is the engine to reuse:
- `post_journal(db, org_id, entry_date, source_type, source_event, description, lines, source_id, reference, actor_account_id, validate_chart=True)`:
  - checks balance with `assert_balanced`;
  - checks every account exists and is active (`_require_active_accounts`);
  - checks the event hasn't already been posted;
  - writes the header and lines **inside the caller's transaction** without committing.
- `reverse_journal` and `ensure_journal_header` (the latter for LEGACY journals).

**`app/domain/accounting/posting_rules.py`** holds pure builders and `PostingLine(account, debit_minor, credit_minor, description, employee_id, department_id, pay_run_id)`. Account slugs are literals there, waiting for the posting-roles phase (audit §20.4).

**Not yet on the engine:** bills, invoices, credit notes, fixed assets, contractor WHT and manual journals still post through the older `post_manual_journal_entry` (`app/services/general_ledger.py`) with no header (`posting.py` docstring). Payroll posts with `validate_chart=False` because of audit P1, which a strict xfail test documents (`tests/unit/test_posting_rules.py`).

### 4.2 Chart of accounts [V]

- **`chart_accounts`:** `org_id`, `code` (slug, unique per org), `name`, `type` (asset, liability, equity, revenue, expense), `is_system`, `is_active`.
- **Defaults** come from `DEFAULT_ACCOUNTS` (`app/services/chart_accounts.py:11`). They are seeded by the `seed-defaults` endpoint, and also when accounting settings switch remittance posting on. New organisations do this at signup.
- **No inventory, GRNI, COGS or inventory-adjustment account exists.** The audit's proposed chart reserves `1400 Inventory`, slug `inventory` (audit §15, line 534).

### 4.3 Missing controls the skill requires [V]

| Control | Status today | Effect on inventory |
|---|---|---|
| Accounting periods / closing | **None** (audit P5; scheduled for audit Phase 15) | The "closed periods cannot be bypassed" invariant can't be enforced yet [D13] |
| Posting-account mappings (roles) | None (audit §20.4) | Inventory account choice is per item / per document until roles exist [P] |
| Report date basis | Reports filter on `ledger_entries.created_at`, not `entry_date` (audit P7) | An inventory journal posted on day N+1 for a receipt dated day N lands on N+1 in existing reports |

### 4.4 Money and quantities [V]

- Money is `BIGINT` minor units throughout (`app/domain/money.py`). Never `float`; `Decimal` is never persisted for money.
- `Numeric` is used in exactly one place (`overtime.hours Numeric(5,2)`). Fractional **quantities** would be a new convention [P]:
  - `NUMERIC(18,4)` in Postgres, `Decimal` in Python;
  - one documented rounding rule when quantity × unit cost becomes minor units.

---

## 5. Vendors and bills

- **`Vendor`** (`app/models/vendor.py`) [V]: `org_id`, optional `contractor_id`, `name`, `contact_email`, `contact_phone`, `tin`. **Reuse it as the supplier model** [P]; no separate supplier table.
- **`Bill`** (`app/models/bill.py`) [V] is **single-line**:
  - fields: `vendor_id`, `bill_number` (unique per org, user-entered), `bill_date`, `due_date`, one `expense_account_code`, `amount_minor`, `vat_minor`, `wht_category`, `wht_amount_minor`;
  - status: `draft → approved → paid`, with `void` reachable only from `draft`.
- **What a bill posts** (`app/services/bills.py`) [V]:
  - On approval: Dr `expense_account_code` (net), Dr `vat_receivable`, Cr `wht_payable`, Cr `accounts_payable`.
  - On payment: Dr AP, Cr `cash`.
  - Both through `post_manual_journal_entry`, so no header.
  - Approval goes through the approval engine (request type `bill`, `app/api/v1/bills.py:63-126`).
- Recurring bills exist (`app/models/recurring_bill.py`) [V].

**Consequences for inventory [A/P]:**

1. **No bill lines, so no three-way match.** Matching purchase order ↔ goods receipt ↔ bill per line needs either a `bill_lines` table or a bill → GRN link. That is a change to bills, so it is a Phase 3 decision [D2].
2. **The receipt-clearing account can ride the existing bill flow.** If receiving posts Dr `inventory` / Cr `grni`, a bill for those goods can set `expense_account_code = "grni"`. Approving it then posts Dr `grni` / Cr AP with **no change to the bill code**, as long as `grni` exists and is active. Price differences between the receipt value and the bill need a purchase-price-variance rule, which also needs the bill → GRN link [D2].

---

## 6. Audit logging and approvals

### 6.1 Audit log [V]

- **`audit_logs`** holds `org_id`, `account_id`, `role`, `action`, `entity_type`, `entity_id` and a JSONB `event_metadata`.
- **`record_audit_event(db, org_id, account_id, role, action, entity_type, entity_id, metadata)`** (`app/services/audit.py`) is called from **routers** after a mutation succeeds.
- **[P]** Every inventory mutation records one audit event, using entity types such as `inventory_item` and `purchase_order`. The frontend audit-log filter keeps a list of entity types (`src/app/(app)/audit-log/page.tsx`), which must be extended to match.

### 6.2 Approvals [V]

The approval engine is generic (`app/models/approval.py`, `app/services/approvals.py`):

- **`approval_workflow_steps`:** per org and request type, ordered, with eligibility by role, direct manager, department head or a specific person.
- **`approval_instances`:** `request_type` + `request_id`, current step and status.
- **`approval_instance_decisions`:** one row per decision.
- **`get_or_create_instance` and `decide`** return `is_final`. Callers act on final approval, as the bill flow does.
- **Request types today:** `leave_request`, `expense`, `bill`.
- **Frontend:** `components/approval-history-panel.tsx` renders the history.

**[P] Reuse it.** Add the request types `purchase_order`, `stock_adjustment`, `stock_issue` and `stock_transfer`. Don't create `inventory_approvals`.

---

## 7. UI conventions and permission model

### 7.1 Roles and permissions [V]

**Roles** (`app/models/membership.py`): `admin`, `payroll_manager`, `accountant` (same rights as `payroll_manager`), `hr_manager`, `manager`, `department_manager`, `auditor` (read-only), `employee`.

**Coarse checks:** `require_roles(...)` is used in **83** places in `app/api/v1`.

**Fine-grained checks exist but aren't used:**
- `Permission` enum and `DEFAULT_ROLE_PERMISSIONS` in `app/domain/permissions.py`;
- per-membership overrides in `membership_permission_overrides`;
- `require_permission` in `app/core/deps.py`, which has **0** callers.

**[P] Make inventory the first module on `require_permission`.** Because it's new, there are no legacy role checks to migrate (consistent with audit Phase 16). New permissions and proposed defaults:

| Permission | admin | payroll_manager / accountant | auditor | hr_manager | department_manager | manager | employee |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `inventory.view` | ✔ | ✔ | ✔ | – | ✔ (own dept issues) [A] | – | – |
| `inventory.manage` (items, categories, units, warehouses, settings) | ✔ | ✔ | – | – | – | – | – |
| `inventory.purchase` (create purchase orders) | ✔ | ✔ | – | – | – | – | – |
| `inventory.approve` (approve POs, adjustments, issues) | ✔ | ✔ [D7] | – | – | – | – | – |
| `inventory.receive` (goods receipts) | ✔ | ✔ [D7] | – | – | – | – | – |
| `inventory.issue` (post issues) | ✔ | ✔ | – | – | request only [D7] | – | – |
| `inventory.transfer` | ✔ | ✔ | – | – | – | – | – |
| `inventory.adjust` / stocktake | ✔ | ✔ | – | – | – | – | – |
| `inventory.valuation` (valuation and GL reports) | ✔ | ✔ | ✔ | – | – | – | – |

These defaults are a starting point for D7. They are not verified business rules.

### 7.2 UI patterns [V]

- **Pages** load data with `useApiResource` (`src/lib/hooks.ts`) and render `LoadingState` / `ErrorState` from `data-state.tsx`.
- **Feedback and dialogs:** `useToast`, plus `ConfirmDialog` and `ConfirmActionButton` for consequential actions.
- **Layout:** `Card`/`CardHeader`, `DataTable`/`Table`, `Badge` for statuses, `KpiTile` for dashboard figures.
- **PDFs** are rendered server-side with ReportLab (`app/services/*_pdf.py`) and downloaded with `downloadAuthenticatedFile`.
- **No CSV/XLSX export utility exists** [V]. CSV appears only for employee import and a pay-run bank file. Inventory report export would add a backend CSV endpoint, following the PDF download pattern [P].
- **No pagination convention.** Only `GET /audit-log` takes `limit` [V]. Stock movement history needs `limit`/`offset` from day one [P].
- **[P] Navigation:** a new top-level "Inventory" group in `nav.ts`, gated per item by role. The nav filter is role-based today.
  - `GET /auth/me` returns only `role`, not permissions [V] (`app/schemas/auth.py:MeResponse`).
  - Effective permissions are exposed only to admins, per membership, at `GET /memberships/{id}/permissions` [V] (`app/api/v1/permissions.py`).
  - Permission-aware navigation would therefore need `/auth/me`, or a new `/auth/me/permissions`, to return the caller's own effective permissions [P]. Until then, nav roles mirror the default permission table above.
  - **The backend is the enforcement point regardless.**

---

## 8. Proposed inventory entities [P]

All tables follow the same rules:

- `org_id` FK to `organisations`, `ENABLE` + `FORCE` RLS and the standard policy;
- UUID primary keys, `created_at timestamptz default now()`, `created_by` (account id);
- quantities are `NUMERIC(18,4)`, money is `BIGINT` minor units.

The `inventory_` prefix keeps the module legible next to the existing 70+ tables.

| Table | Purpose / key columns | Integrity |
|---|---|---|
| `inventory_settings` | Per-org policy: `enabled`, `allow_negative_stock` (default false), `over_receipt_tolerance_pct` (default 0), `costing_method` (`weighted_average`) | One row per org |
| `inventory_categories` | `name`, `parent_id` (self FK) | Unique `(org_id, parent_id, name)` |
| `inventory_units` | `code` (e.g. `PCS`, `KG`), `name`, `allows_fraction` | Unique `(org_id, code)` |
| `inventory_items` | `sku`, `name`, `description`, `item_type` (stock, non_stock, consumable, service), `category_id`, `base_unit_id`, `reorder_level`, `max_level`, `preferred_vendor_id → vendors`, `inventory_account_code`, `consumption_account_code`, `cogs_account_code` (slugs validated against `chart_accounts`), `track_lots`, `track_serials`, `track_expiry`, `barcode`, `is_active` | Unique `(org_id, sku)`. Items are archived, never deleted. Unit and type are immutable once a movement exists. |
| `inventory_item_units` | `item_id`, `unit_id`, `factor_to_base NUMERIC(18,6) > 0`, `purpose` (purchase / issue) | Unique `(item_id, unit_id)` |
| `inventory_warehouses` | `code`, `name`, `branch_id → branches`, `address`, `is_active` | Unique `(org_id, code)` |
| **`inventory_stock_movements`** | **The authority.** `item_id`, `warehouse_id`, `movement_type` (receipt, issue, transfer_out, transfer_in, adjustment_gain, adjustment_loss, reversal), signed `quantity_base`, `unit_cost_minor`, signed `value_minor`, `entry_date`, `source_type`, `source_id`, `source_line_id`, `reversal_of_id`, `journal_entry_id`, `lot_id`, `reason`, `posted_by` | Append-only via the existing `forbid_update_delete()` trigger. Unique `(org_id, source_type, source_line_id, movement_type)` (idempotency). Unique `reversal_of_id`. Indexes on `(org_id, item_id, warehouse_id, entry_date)` and `(org_id, source_type, source_id)`. |
| `inventory_stock_balances` | Projection: `item_id`, `warehouse_id`, `quantity_base`, `value_minor` | PK `(item_id, warehouse_id)`. Written **only** by the posting service in the same transaction as the movement, with `SELECT … FOR UPDATE`. A test asserts it equals `SUM(movements)`. |
| `inventory_item_costs` | Per-org-item moving average: `quantity_base`, `value_minor` | Locked `FOR UPDATE` on every valued movement |
| `purchase_orders` / `purchase_order_lines` | `po_number` (generated per org), `vendor_id`, `status` (draft, submitted, approved, issued, partially_received, received, closed, cancelled), dates; lines with `item_id`, `unit_id`, `quantity`, `unit_price_minor`, `received_quantity_base` | Unique `(org_id, po_number)`. Status changes only through service transitions. |
| `goods_receipts` / `goods_receipt_lines` | `grn_number`, `purchase_order_id`, `warehouse_id`, `receipt_date`, `status` (draft, posted, reversed); lines with `po_line_id`, `accepted_quantity`, `rejected_quantity`, lot / serial / expiry | Over-receipt is blocked unless the tolerance allows it. Posting is idempotent through the movement unique key. |
| `stock_issues` / `stock_issue_lines` | `issue_number`, `warehouse_id`, `department_id`, `requested_by_employee_id`, `purpose`, `status` (draft, pending_approval, approved, posted, rejected, reversed) | |
| `stock_transfers` / `stock_transfer_lines` | `from_warehouse_id`, `to_warehouse_id`, `status` (draft, approved, dispatched, received, closed), `dispatched_at`, `received_at`; lines with `dispatched_qty`, `received_qty` | `from ≠ to`, same org. In-transit is modelled explicitly [D5]. |
| `stock_adjustments` / `stock_adjustment_lines` | `reason_code` (damage, expiry, loss, found, correction, write_off), `notes`, `status`; lines with `expected_qty`, `counted_qty`, `variance_qty` | Material adjustments are routed through the approval engine [D8] |
| `stocktakes` / `stocktake_lines` | `warehouse_id`, `cutoff_at`, `status` (open, counting, review, posted); lines with `snapshot_qty` (as at cutoff), `counted_qty` | The variance posts as a `stock_adjustment` referencing the stocktake [D6] |
| `inventory_lots` | `item_id`, `lot_code`, `expiry_date` | Only if D9 = yes |

**Reused, not duplicated:** `vendors`, `branches`, `departments`, `employees`, `chart_accounts`, `journal_entries` / `ledger_entries` (through `post_journal`), the `approval_*` tables, `audit_logs` and `accounting_settings` patterns.

### 8.1 Stock-ledger posting algorithm [P]

There is one service, `app/services/inventory_posting.py`, with pure rules in `app/domain/inventory/`.

Every posting runs in **one database transaction**, which is the request's `tenant_session`:

1. Validate the document state and organisation ownership of every referenced id.
2. Lock the rows in a fixed order to avoid deadlocks: `inventory_item_costs`, then `inventory_stock_balances` for each affected (item, warehouse), in sorted order, all `FOR UPDATE`.
3. Compute quantity and value deltas in the pure domain layer: weighted average, rounding and the negative-stock check.
4. Insert movements. The unique key turns a retry into a no-op or a 409.
5. Update balances and costs.
6. Build `PostingLine`s and call `post_journal(source_type=INVENTORY_*, source_id=document.id, source_event=...)`. Its own unique index blocks a double post.
7. Move the document to its posted status, then call `record_audit_event`.

Any failure rolls back everything, so stock and accounting can't diverge (invariant 15). No outbox is needed because stock and the GL share one Postgres database.

---

## 9. Costing and accounting integration [P]

**Costing.** No costing policy exists today [V]. The proposal [D1] is a **moving weighted average per organisation and item**:
- An average shared across all warehouses makes transfers value-neutral automatically (invariant 7).
- Receipts change the average. Issues are valued at the current average and never re-cost history.
- **Rounding:** `value_minor = round_half_even(qty × average)`. When an issue empties the item's total quantity, it takes the whole remaining value, so no residue drifts.
- **Backdated movements** do **not** revalue later issues. They use the average at posting time, and the accounting date is the document date (`entry_date`) [D13].

**Accounts** to seed for organisations that enable inventory [P]:

| Account | Type | Notes |
|---|---|---|
| `inventory` | asset | Audit 1400 |
| `grni` (goods received not invoiced) | liability | |
| `inventory_adjustment` | expense | Write-offs and losses; gains credit it |
| `cogs` (cost of goods sold) | expense | Only if resale is in scope [D10] |

**Seed lazily, not through a backfill migration.** Seed when an organisation turns inventory on, the same way accounting settings seed the chart today. That avoids the audit's P24 risk, where backfill migrations insert nothing under a non-bypass role.

**Events** use `post_journal`, with new `JournalSourceType` values [P]:

| Event | Dr | Cr | `source_type` / `source_event` |
|---|---|---|---|
| GRN posted | `inventory` (or the item's inventory account) | `grni` | `inventory_receipt` / `posted` |
| Bill for received goods | `grni` (bill `expense_account_code`), `vat_receivable` | `accounts_payable`, `wht_payable` | Existing bill flow, unchanged [D2] |
| Issue posted | the item's consumption account (with `department_id` dimension) | `inventory` | `inventory_issue` / `posted` |
| Write-off / loss | `inventory_adjustment` | `inventory` | `inventory_adjustment` / `posted` |
| Found stock / gain | `inventory` | `inventory_adjustment` | `inventory_adjustment` / `posted` |
| Transfer | no journal (one inventory account, value-neutral) | – | movements only |
| Reversal | mirrored lines through `reverse_journal` | | `reversal` |

Journals use `validate_chart=True` always. If a mapped account is missing or inactive, posting fails with a 400 that says what to configure.

---

## 10. Migration dependencies and integration risks

| # | Risk / dependency | Severity | Mitigation |
|---|---|---|---|
| R1 | `journal_source_type` and `approval_request_type` are Postgres enums. New values need `ALTER TYPE … ADD VALUE`, and a value can't be **used** in the same transaction that adds it [V: enums in `app/models/journal_entry.py`, `app/models/approval.py`] | Medium | Add enum values in their own migration, before any migration or code that writes them |
| R2 | No accounting periods (audit Phase 15) [V] | **High** for GL posting | Don't post inventory to the GL until D13 is decided. Either implement periods first, or add an interim per-org `books_locked_through` date checked by the inventory posting service |
| R3 | Reports filter on `created_at`, not `entry_date` (audit P7) [V] | Medium | The inventory ↔ GL reconciliation report uses `journal_entries.entry_date`. Document the mismatch with the existing financial statements until P7 is fixed |
| R4 | Bills have no lines and no link to a goods receipt [V] | Medium | Phase 3 adds a bill ↔ GRN link (or bill lines) for GRNI clearing and price variance [D2] |
| R5 | Chart P1 is still open (payroll accounts missing from `DEFAULT_ACCOUNTS`) [V] | Low for inventory | Inventory seeds its own accounts lazily. Don't add more `validate_chart=False` calls |
| R6 | Backfill migrations under a non-`BYPASSRLS` role insert nothing (audit P24; Railway role unverified, A24) [V/A] | Medium | No inventory backfills; seed on enable |
| R7 | Desktop runs as a database superuser, so RLS is bypassed [V] | Medium | Cloud-only RLS isolation tests. Application-layer org checks are mandatory (§2) |
| R8 | The skill's `NUMERIC` quantities are a new convention next to integer money [V] | Low | Pure `Decimal` domain functions with Hypothesis property tests; quantities never reach floats in the API (serialise as strings) [P] |
| R9 | No frontend test runner [V] | Medium | E2E needs Playwright added as a dev dependency [D16]. A Chromium build is available in this environment |
| R10 | Concurrency: two issues racing for the last units [P] | **High** | `FOR UPDATE` locks in a fixed order (§8.1), plus a concurrent-issue integration test using two sessions |
| R11 | Cloud/desktop parity (A28) [V] | Medium | Each backend PR also ported to `desktop_plutus_hr-backend` in the same revision order |
| R12 | Production hosting: Railway `plutus-api` and Postgres are offline as of 2026-10-11 (expired trial) [V] | **High** operationally; doesn't block development | Restore billing before deploying any inventory migration |
| R13 | `562458d` reached `main` without a PR [V] | Process | Inventory follows branch → PR → CI → merge (the chosen workflow) |
| R14 | No pagination convention [V] | Low | Inventory list endpoints take `limit`/`offset` and return totals |

**Migration order [P].** Forward-only. Each step is additive and reversible with `downgrade` until data exists.

1. Enum values (`journal_source_type`: `inventory_receipt`, `inventory_issue`, `inventory_adjustment`, `inventory_transfer`; `approval_request_type`: `purchase_order`, `stock_issue`, `stock_adjustment`, `stock_transfer`).
2. Master data: `inventory_settings`, categories, units, items, item units, warehouses.
3. Ledger: stock movements (append-only trigger), balances, item costs.
4. Documents: purchase orders, goods receipts, issues, transfers, adjustments, stocktakes (and lots, if D9).

Every table has RLS from its first migration. Once posted movements exist, the downgrade path is "restore from backup" for the cloud database, and "back up `pgdata` before first launch of the new version" for desktop (audit §26.7).

---

## 11. Implementation phases and verification

### Verification commands (all verified to run in this environment) [V]

**Backend:**
```bash
uv sync --locked --dev
uv run ruff check . && uv run ruff format --check . && uv run mypy app
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/plutus_test uv run alembic upgrade head   # fresh DB
DATABASE_URL=... uv run pytest            # needs a fresh database each full run
```

**Frontend:**
```bash
npm ci && npx tsc --noEmit && npm run lint && npm run build
```

Desktop repos use the same commands. The installer build is the `Build desktop app` workflow (`workflow_dispatch`).

### Prioritised plan [P]

| Phase | Scope | Exit criteria |
|---|---|---|
| **0** | This report; decide §12 | D1–D10 and D13 answered |
| **1 Foundation** | `inventory_settings`, categories, units, items, warehouses; permissions (`require_permission` + `DEFAULT_ROLE_PERMISSIONS`); stock ledger, balances and item costs; posting service with **opening-balance** and **adjustment** movements only, and **no GL posting**; audit events; Inventory nav group with Items, Warehouses, Stock on hand and Movements pages | Migrations replay; unit tests (conversions, average cost, rounding, negative-stock rule); integration tests (org isolation, idempotent posting, concurrent issue, balance = Σ movements); `tsc`/lint/build pass; desktop port |
| **2 Operations** | Purchase orders (approval engine), goods receipts (partial, tolerance), issues, transfers (in-transit), reversals, document history panels | State-machine tests, over-receipt and duplicate-request tests, two-session concurrency tests |
| **3 Accounting** | New source types; account seeding on enable; GRN, issue and adjustment journals through `post_journal`; bill ↔ GRN link and GRNI clearing [D2]; period guard [D13]; inventory ↔ GL reconciliation | Every posted document has exactly one journal; reconciliation report = 0 difference in tests; failure-rollback test |
| **4 Control & reporting** | Stocktakes with cutoff, reorder suggestions, lots and expiry [D9], valuation / movement / variance reports, CSV + PDF export | Report totals reconcile to the ledger |
| **5 Hardening** | Playwright E2E for the 10 skill workflows [D16], accessibility pass, performance indexes, runbook | Full regression green on cloud and desktop; installer smoke test |

### Risks to resolve before **any** inventory transaction posts to the GL

1. **D13: period control.** Without it, a backdated receipt can land in a month that has already been reported, and nothing stops it.
2. **D1 and D2: costing method and receipt accounting** (GRNI or not, and how bills clear it). They decide which accounts move and when.
3. **R10: concurrency.** The locking scheme must be proven by a two-session test before balances are trusted.
4. **Account seeding and validation.** `inventory` and `grni` (and `inventory_adjustment`, `cogs`) must exist and be active per org. Posting must use `validate_chart=True`.
5. **R1: enum migration order.** Otherwise the first deploy that posts an inventory journal fails.
6. **R12: production hosting restored.** Plus a confirmed migration role (A24) and a database backup before the first inventory migration runs in production.

---

## 12. Business decisions

**Approved 2026-10-12.** The product owner approved every proposed default below as-is ("Approve the defaults and start phase 1"). Each default now counts as the decision; a later change is a new decision recorded here. Where a decision needs machinery a later phase builds, it applies from that phase:

- D2, D13 and D14: Phase 3, when inventory first posts to the GL.
- D4 and D5: Phase 2 (receipts, transfers).
- D6, D9: Phase 4.
- D8: Phase 2. Phase 1 has no approval step, so its adjustments are posted directly by `inventory.adjust` holders. Approval routing for write-offs arrives with the approval engine wiring in Phase 2.
- D16: Phase 5.
- D11: a later phase.


| # | Decision | Proposed default |
|---|---|---|
| D1 | Costing method | Moving weighted average per org and item |
| D2 | Receipt accounting: accrue at receipt (Dr inventory / Cr GRNI, bill clears GRNI) or recognise only at bill approval | Accrue at receipt (GRNI) |
| D3 | Negative stock | Rejected (`allow_negative_stock = false`) |
| D4 | Over-receipt tolerance | 0% |
| D5 | Transfers: instant, or dispatch → in-transit → receipt | In-transit, with dispatch and receipt steps |
| D6 | Stocktake cutoff: freeze the warehouse, or snapshot at cutoff and post the variance against the snapshot | Snapshot at cutoff; movements after the cutoff don't affect the count |
| D7 | Who may receive, issue, approve and adjust | §7.1 table |
| D8 | Approval threshold for adjustments (value above which approval is needed) | All write-offs need approval; gains under a configurable amount auto-approve |
| D9 | Lot, serial and expiry tracking needed in v1? | Lots and expiry yes, serials later |
| D10 | Scope: internal consumption only, or resale too? Invoices are single-line with no item link today [V], so resale needs invoice lines and COGS posting | Internal consumption first; resale is a later phase |
| D11 | Inventory vs fixed-asset boundary: durable equipment received through a PO | Items flagged `capitalise` can't be stocked; their receipt creates a fixed asset (later phase) |
| D12 | Quantity precision | `NUMERIC(18,4)`; units flagged `allows_fraction = false` reject fractions |
| D13 | Period control before GL posting | Implement audit Phase 15 (periods) first, or an interim per-org lock date |
| D14 | VAT on inventory purchases | Keep the existing bill VAT flow (`vat_receivable`); no VAT at receipt |
| D15 | Enable per organisation, and from which edition | Opt-in per org (`inventory_settings.enabled`), both editions |
| D16 | Add Playwright to the frontend for E2E | Yes, dev dependency only |
| D17 | Brand: the site now says PlutusBiztech, the app says Plutus Technologies | Out of scope here; affects inventory PDFs' headers |

---

## 13. Phase 1 implementation record

What Phase 1 built, and where it settled a detail the proposals left open. Migration `99fdc31abd02` (revises `4f1c9a7e2b30`).

### 13.1 Built

**Tables.** All 11 have org-scoped RLS (ENABLE + FORCE, the standard `app.current_org` policy):

- `inventory_settings` (one row per org; `enabled`, `costing_method`, adjustment numbering);
- `inventory_categories` (nested, cycle-checked) and `inventory_units`;
- `inventory_items` and `inventory_item_units` (alternative units with a factor to the base unit);
- `inventory_warehouses` (optional `branch_id`);
- `inventory_adjustments` and `inventory_adjustment_lines`;
- `inventory_stock_movements` (the stock ledger; append-only via `forbid_update_delete()`);
- `inventory_stock_balances` (quantity per item and warehouse);
- `inventory_item_costs` (the weighted-average pool per item).

**Domain** (`app/domain/inventory/`, pure):

- `quantities.py`: NUMERIC(18,4), never rounds, exact unit conversion, whole-number units;
- `costing.py`: the moving weighted average, half-even rounding; the last unit out takes the remaining value.

**Services:**

- `app/services/inventory.py`: settings and master data;
- `app/services/inventory_posting.py`: adjustment documents and `post_movements`, the single stock-posting entry point later phases reuse;
- `app/services/inventory_queries.py`: read models.

**API.** `app/api/v1/inventory.py` under `/api/v1/inventory`:

- `settings`, `summary`;
- `categories`, `units`;
- `items` (+ `items/{id}/units`);
- `warehouses`;
- `adjustments` (+ `/{id}/post`, `/{id}/reverse`);
- `stock`, `movements`.

Every endpoint except `settings` and `summary` answers 409 until the module is enabled. Every write records an audit event (`inventory_*.create|update|post|reverse|delete`).

**Permissions.** These are the first endpoints on `require_permission`. Phase 1 adds the four permissions it needs. `purchase`, `approve`, `receive`, `issue` and `transfer` arrive with the documents that use them in Phase 2.

| Permission | admin | payroll_manager / accountant | auditor | others |
|---|:-:|:-:|:-:|:-:|
| `inventory.view` | ✔ | ✔ | ✔ | – |
| `inventory.manage` | ✔ | ✔ | – | – |
| `inventory.adjust` | ✔ | ✔ | – | – |
| `inventory.valuation` | ✔ | ✔ | ✔ | – |

`department_manager` gets no inventory access yet: the "own department issues" view (§7.1) needs issues, which arrive in Phase 2. Per-membership overrides work as for every other permission. Values and costs are left out of responses (returned as `null`) unless the caller holds `inventory.valuation`.

**Frontend** (`plutus-hr-system-frontend`):

- an **Inventory** nav group (roles mirror the default grants above);
- **Overview** (KPIs and recent movements), **Items** (with unit conversions), **Stock on Hand**, **Stock Adjustments** (list, new, detail with post, reverse, edit and delete) and **Stock Movements** (filtered, paged ledger);
- **Warehouses** and **Inventory Settings** (switch on/off, units, categories);
- the four permissions on the Permissions page, and the inventory entity types in the Audit Trail filter.

Every page shows a "switched off" notice, with a link to Settings for managers, until the module is enabled.

### 13.2 Settled during Phase 1

- **One cost pool per item, quantities per warehouse.** The weighted average (D1) is held once per item across the organisation in `inventory_item_costs`. Balances hold quantity only. A warehouse's value is shown as its quantity × the item's average, so moving stock between warehouses (Phase 2) can never change its value.
- **Opening balances are adjustments** with reason `opening_balance` (movement type `opening_balance`). There's no separate import path yet.
- **Reasons fix the direction:**
  - `opening_balance` and `found` only add stock;
  - `damage`, `expiry`, `loss` and `write_off` only remove it;
  - `correction` does either.
  - Increases need a unit cost (it defaults to the item's default cost, scaled to the line's unit). Decreases must not carry one: they leave at the average.
- **Reversal.** A posted adjustment is corrected by reversal, never by editing. Reversal writes compensating `reversal` movements dated today (Lagos):
  - stock the adjustment removed comes back at the value it left at;
  - stock it added leaves at the current average, like any removal.
  - The difference is a cost variance, which Phase 3 will post. A reversal is refused if the stock it would remove has already been used.
- **Negative stock (D3)** is rejected by the service and backed by check constraints on balances and the cost pool.
- **Concurrency.** A posting locks the cost rows of its items, then their balance rows, `FOR UPDATE` in sorted order, before reading anything. A unique `(org, source type, source line, movement type)` key makes double-posting structurally impossible.
- **Frozen once used.** An item's type and base unit, and a unit's `allows_fraction`, can't change after stock has moved. A warehouse holding stock can't be deactivated.
- **Tenant isolation doesn't depend on the database role.** RLS only binds a non-superuser connection. The desktop's embedded database runs as the superuser `plutus` (audit §2.4), and the Railway role is unverified (A24). So every inventory model is `OrgScoped` (`app/models/base.py`): `app/core/db.py` adds `org_id = <session org>` to every ORM SELECT on those models (via `with_loader_criteria`, including joins and subqueries) for any tenant or system session. Other modules still rely on RLS alone. On a superuser connection they are **not** isolated, which is a pre-existing gap outside this phase (see §13.4).
- **No GL posting** (as planned). Movements carry values so Phase 3 can post them, but nothing in Phase 1 touches `journal_entries`.

### 13.3 Verified

- `ruff check .`, `ruff format --check .` and `mypy app` (strict) are clean.
- `alembic upgrade head` succeeds on a fresh database, and the migration was tested upgrade → downgrade → upgrade. `alembic check` shows no inventory drift.
- Unit tests cover quantities and costing. Hypothesis properties cover cost-pool conservation, no negative pool, and no orphaned value.
- `tests/integration/test_api_inventory.py` covers:
  - enablement, master-data rules, weighted average and reversal;
  - unit conversion, reason, cost and date rules, negative-stock refusal, drafts and summary;
  - the permission matrix, including overrides and value hiding;
  - cross-org isolation and the append-only trigger;
  - a two-connection concurrent-posting test, which fails (oversells) when the row locks are removed;
  - a superuser (RLS-bypassing) session test, which shows each org's data leaking into the other when the ORM org scoping is removed;
  - balance = Σ movements, and pool value = Σ movement values, after every scenario.
- The full backend suite on a fresh database gives 605 passed and 1 xfail. The xfail is pre-existing and unrelated.
- Frontend: `tsc --noEmit`, `eslint` and `next build` are clean.
- An end-to-end browser run (Playwright/Chromium against a local API) covered the whole Phase 1 flow:
  - sign up, switch inventory on, create a category, a warehouse and an item with a BOX = 5 PCS conversion;
  - post an opening balance of 40 BOX (200 PCS, ₦1,000,000);
  - post a damage of 5 PCS from a draft (stock 195 PCS, ₦975,000), then reverse it;
  - refuse an over-removal and keep it as a draft, then delete the draft;
  - check the ledger, the overview and the audit trail.

  The script is not committed. Playwright joins the repo in Phase 5 (D16).

### 13.4 Not in Phase 1

The following are not in Phase 1:

- purchase orders, goods receipts, issues and transfers (Phase 2);
- approval routing for adjustments (D8, Phase 2);
- GL posting, account seeding and the period guard (Phase 3);
- stocktakes, lots and expiry, and reports and exports (Phase 4);
- Playwright E2E (Phase 5).

Found while building Phase 1, outside its scope:

- **RLS is not enforced on a superuser connection** (desktop today, and possibly Railway, A24). Inventory is protected by its own org scoping (§13.2). Every other module relies on RLS alone. There are two fixes:
  - connect the app as a non-superuser role (`NOBYPASSRLS`), keeping a superuser only for migrations;
  - or extend `OrgScoped` to the other org-owned models.

---

## 14. Phase 2 implementation record

What Phase 2 (Operations) built, and where it settled a detail the proposals left open. Migration `b7e41c2d9a63` (revises `99fdc31abd02`). Still **no GL posting**: every document moves stock and value in the stock ledger only. Phase 3 posts the journals.

### 14.1 Built

**Tables.** Eight new, all with org-scoped RLS (ENABLE + FORCE) and `OrgScoped` ORM scoping:

- `inventory_purchase_orders` and `inventory_purchase_order_lines`;
- `inventory_goods_receipts` and `inventory_goods_receipt_lines` (one row per PO line per receipt);
- `inventory_stock_issues` and `inventory_stock_issue_lines`;
- `inventory_stock_transfers` and `inventory_stock_transfer_lines`.

**Changes to Phase 1 tables:**

- `inventory_settings` gains document numbering for each type, `over_receipt_tolerance_bp` (D4, default 0), `adjustment_gain_approval_limit_minor` (D8, null = gains never need approval), `require_issue_approval` (default on) and `require_transfer_approval` (default off).
- `inventory_warehouses.is_transit` marks the one in-transit location per org (code `IN-TRANSIT`, a partial unique index). It's created on first dispatch, hidden from warehouse lists unless asked for, and can't be edited or chosen on a document.
- `inventory_adjustments` gains `pending_approval`, `approved` and `rejected` statuses, with submitted and decided stamps.
- The movement idempotency key becomes `(org, source type, source line, movement type, warehouse)`. A transfer line legitimately posts the same movement type twice, once at each end.

The migration was tested upgrade → downgrade → upgrade.

**Lifecycles:**

| Document | States |
|---|---|
| Purchase order | draft → pending_approval → approved \| rejected; approved → issued → partially_received → received; partially_received → closed (short); draft/pending/approved/issued → cancelled while nothing is received |
| Goods receipt | draft → posted → reversed |
| Stock issue | draft → pending_approval → approved \| rejected; approved → posted → reversed; anything unposted → cancelled |
| Stock transfer | draft → pending_approval → approved \| rejected; approved → in_transit → received; anything undispatched → cancelled |
| Adjustment | draft → pending_approval → approved \| rejected → posted → reversed (D8); draft → posted directly when no approval is needed |

When issue or transfer approval is switched off, submitting approves at once, and a draft can be posted or dispatched directly. Rejected documents can be deleted, and so can drafts. Numbers are per org and per type: `PO-`, `GRN-`, `ISS-`, `TRF-`, `ADJ-` plus six digits.

**Services** (`app/services/`):

- `inventory_common.py`: line and unit resolution, document numbering, status guards, the transit warehouse, reversal plans and the approval-engine wiring;
- `inventory_adjustments.py`: adjustments moved here from `inventory_posting.py`, which now holds only the posting engine (`post_movements`);
- `inventory_purchasing.py`: purchase orders and goods receipts (pure maths in `app/domain/inventory/purchasing.py`);
- `inventory_issues.py` and `inventory_transfers.py`;
- `inventory_document_queries.py`: list and detail read models.

**API.** `app/api/v1/inventory_operations.py`, under `/api/v1/inventory`:

- `purchase-orders`: CRUD, plus `/{id}/submit|approve|reject|issue|cancel|close`;
- `goods-receipts`: CRUD, plus `/{id}/post|reverse`;
- `issues`: CRUD, plus `/{id}/submit|approve|reject|cancel|post|reverse`, and `issues/departments`;
- `transfers`: CRUD, plus `/{id}/submit|approve|reject|cancel|dispatch|receive`;
- `adjustments/{id}/submit|approve|reject`, added to `app/api/v1/inventory.py`.

Every write records an audit event (`inventory_purchase_order.*`, `inventory_goods_receipt.*`, `inventory_stock_issue.*`, `inventory_stock_transfer.*`). Values are hidden from callers without `inventory.valuation`, as in Phase 1.

**Approvals.** Four new request types: `purchase_order`, `stock_adjustment`, `stock_issue` and `stock_transfer`. They go through the shared engine (`app/services/approvals.py`) and its configurable workflow steps:

- **Requesterless types.** Purchase orders, adjustments and transfers have no requesting employee, like bills. The engine refuses direct-manager and department-head steps for them (`REQUESTERLESS_REQUEST_TYPES`).
- **Stock issues carry the requesting employee**, so they can route to that employee's manager or department head.
- `/approval-instances/{type}/{id}` serves an inventory document's history to `inventory.view` holders, and a stock issue's history to `inventory.request` holders too.

**Permissions.** The other five Phase 2 permissions, plus `inventory.request`:

| Permission | admin | payroll_manager / accountant | auditor | department_manager |
|---|:-:|:-:|:-:|:-:|
| `inventory.purchase` | ✔ | ✔ | – | – |
| `inventory.approve` | ✔ | ✔ | – | – |
| `inventory.receive` | ✔ | ✔ | – | – |
| `inventory.issue` | ✔ | ✔ | – | – |
| `inventory.transfer` | ✔ | ✔ | – | – |
| `inventory.request` | ✔ | ✔ | – | ✔ |

`inventory.request` is D7's department-manager request. A holder raises, edits, submits and cancels issues only for departments they head, sees only those issues, and can read the item and warehouse catalogue to fill them in. They never see stock levels, values or the ledger. Posting and reversing stay with `inventory.issue`.

**Frontend** (`plutus-hr-system-frontend`):

- The Inventory nav group is split into **Stock**, **Operations** and **Setup**.
- **Operations** holds Purchase Orders, Goods Receipts, Stock Issues (also shown to department managers), Stock Transfers and Stock Adjustments. Each has a list with a status filter, a draft form, and a detail page.
- The detail pages offer status-appropriate actions and an **approval card**: the history, plus approve/reject with a comment while the document waits.
- Receipt, issue and transfer pages show the stock movements the document wrote. Each movement links back to its source document.
- **"Receive goods"** on a purchase order opens a receipt prefilled with the outstanding quantities, in the ordered unit.
- **Transfers** are received in a drawer, line by line. A shortfall needs a reason.
- **Adjustments:** "Save and post" submits for approval instead when D8 requires it. Approved adjustments are posted from the detail page.
- **Inventory Settings** gains an Operations card: tolerance %, gain approval limit, and the issue and transfer approval switches.
- The **Overview** gains Awaiting approval, Open purchase orders and Transfers in transit.
- **Approval Workflows** lists the four new request types and hides manager steps for the requesterless ones. **Permissions** and the **Audit Trail** filter list the new permissions and entity types.

### 14.2 Settled during Phase 2

- **Receipts are valued at the net order price.** `round(accepted × (ordered × price − discount) / ordered)`, in the base unit (`receipt_value_minor`). The line tax is recorded and totalled, but it never enters stock value: D14 leaves VAT with the vendor bill (Phase 3). Only stock and consumable items move stock. Non-stock and service lines are received for the order's progress only.
- **Over-receipt (D4)** is checked per line against ordered × (1 + tolerance) in base units, rounded down to the stored 4 decimals. It's checked at save and again at post, so a receipt that fits on save but is overtaken by another is refused at post. Rejected quantities need a reason and never enter stock.
- **Receipts against one order serialise.** Posting locks the receipt, then its purchase order, so two concurrent receipts can't both pass the tolerance check. A two-thread test proves it, and fails when the order lock is removed.
- **A partly received order is closed short, not cancelled.** Cancelling is only for an order nothing has been received against, with no draft receipts waiting.
- **Receipt reversal** takes the goods back out at the current average (like any removal) and reopens the order's quantities. It's refused once the stock has been used, or the order closed.
- **Issues and adjustment write-offs leave at the moving average.** Reversing an issue puts the stock back at the value it left at.
- **Transfers are value-neutral pairs (D5).** Dispatch posts out of the source and into `IN-TRANSIT`, and receipt posts out of transit and into the destination. Each "in" is valued at exactly the paired "out", so the organisation's stock value is unchanged by a transfer. Every line must be accounted for at receipt. A shortfall is written off from transit as an `adjustment_loss` with reason "transit loss: …" and a required discrepancy reason. Movement dates default to today and can't be in the future, or before the transfer date.
- **Adjustment approval (D8).** Any line that removes stock makes the whole adjustment need approval. Otherwise the value added is compared with `adjustment_gain_approval_limit_minor`: at or above the limit needs approval, and no limit means gains never do.
- **Who signs a step is the engine's call.** With no workflow steps configured, Admin, Payroll Manager or Accountant can decide.
  - The decision endpoints also require `inventory.approve`.
  - For stock issues, `inventory.request` is enough to reach the endpoint, so a department head can sign a department-head step. The engine then refuses anyone the current step doesn't name.
- **Foreign ids are checked against the caller's org** before use: vendor, branch, department and employee, which aren't `OrgScoped`. This matters on a superuser connection (§13.4). During the local end-to-end run on a superuser connection, the vendor list showed another org's vendor, and the purchase order service refused it with "vendor not found".

### 14.3 Verified

- `ruff check .`, `ruff format --check .` and `mypy app` (strict) are clean. `alembic upgrade head` succeeds on a fresh database.
- `tests/unit/test_inventory_purchasing.py` covers the purchasing maths: net value, rounding and the tolerance limit.
- `tests/integration/test_api_inventory_operations.py` covers:
  - partial receipts, receipt reversal and closing short;
  - the tolerance limit, and purchase order rules (dates, warehouses, cancel and close guards);
  - concurrent receipts against one order;
  - the issue flow at average cost with reversal;
  - department-manager requests and scope;
  - a department-head workflow step signed by the head;
  - transfers through transit with a shortfall, and transfer rules;
  - D8 adjustment approval;
  - configured multi-step workflows;
  - the permission matrix and cross-org isolation;
  - balance = Σ movements after every scenario.
- `tests/integration/test_api_inventory.py` covers the Phase 1 scenarios, updated for D8.
- Full backend suite on a fresh database: 625 passed, 1 xfail (pre-existing, unrelated).
- Frontend: `tsc --noEmit`, `eslint` and `next build` are clean.
- An end-to-end browser run (Playwright/Chromium) covered:
  - the operations settings;
  - a purchase order of 10 BOX with discount and tax (total ₦258,750), through approval and issue;
  - a receipt of 6 BOX with 1 rejected (₦144,000 at the net price), then a second receipt refused beyond the 10% tolerance and accepted at 4 BOX;
  - an issue of 10 PCS through approval (₦48,000 at average);
  - a transfer of 5 PCS with 1 lost in transit;
  - a write-off routed through approval;
  - closing stock of 34 + 4 PCS, the overview KPIs, the workflow request types and the audit trail.

  The browser ran against a local API connected as a non-superuser role (RLS enforced). The script is not committed (Playwright arrives in Phase 5, D16).

### 14.4 Known limitations

- **No self-approval block.** A user eligible for a step can approve a document they raised. Use a workflow naming a different role or person where segregation of duties matters.
- **Transfers can't be reversed once dispatched.** Correct one with a transfer back.
- **An issue is returned only whole,** by reversal. A partial return is an adjustment (`found`/`correction`) or a new issue for the rest.
- **Line managers (role `manager`) hold no inventory permission.** A direct-manager step on stock issues needs them to be granted `inventory.request` by override, or the step should name a department head or role instead.
- **No GL posting or bill ↔ receipt matching yet (Phase 3).** Receipts, issues and write-offs carry their values in the ledger for Phase 3 to post.
- **No purchase order PDF yet,** and no email to the vendor.
