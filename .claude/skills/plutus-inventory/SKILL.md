---
name: plutus-inventory
description: Design, implement, test, and integrate an enterprise-grade inventory and stock-control subsystem into the existing Plutus HR, payroll, and accounting platform. Use when adding inventory, stock management, warehouses, procurement, goods receipts, stock issues, transfers, stocktakes, inventory valuation, or inventory-to-accounting integration.
---

# Plutus Inventory Management — Software Architecture and Implementation Skill

## 1. Mission

Act as a principal software architect and senior full-stack engineer working inside the existing Plutus HR and Payroll repository.

Implement a production-quality inventory management subsystem that integrates with existing accounting, vendors, bills, chart of accounts, fixed assets, organizational structure, authentication, permissions, audit logs, and reporting.

This is an extension of an existing business application, not a new application.

**Primary objectives**

- Preserve existing application behavior and architectural conventions.
- Implement inventory workflows with reliable, auditable stock movements.
- Maintain strict organization and branch data isolation.
- Integrate inventory financial events with the existing accounting system.
- Deliver complete, responsive, accessible user interfaces.
- Include database migrations, authorization, validation, automated tests, and documentation.
- Avoid mock-only features, duplicated accounting logic, placeholder actions, and disconnected frontend pages.

## 2. Mandatory repository reconnaissance

Before changing files, inspect the repository and establish the actual architecture.

Read, where available:

- Root README and contributor instructions.
- CLAUDE.md, AGENTS.md, and existing `.claude/skills/`.
- Package manifests, workspace configuration, lockfiles, and scripts.
- Existing Next.js App Router route groups and navigation configuration.
- Authentication and Supabase server/client initialization.
- Organization and branch resolution.
- Role definitions, permission helpers, and RLS policies.
- Existing accounting schemas and posting functions.
- Chart of accounts and general ledger models.
- Vendor, supplier bill, customer, budget, fixed-asset, and audit-log implementations.
- Shared components, design tokens, forms, tables, dialogs, notifications, and reporting utilities.
- Existing migrations and testing conventions.

Use targeted file searches and inspect the actual implementations before designing new interfaces.

### Architecture discovery report

Create `docs/architecture/inventory-integration.md` documenting:

1. Actual application and package structure.
2. Authentication and tenant-isolation strategy.
3. Existing organization, branch, and warehouse-related models.
4. Existing accounting transaction and journal-posting contracts.
5. Existing vendor and bill relationships.
6. Existing audit logging and approval workflows.
7. Existing UI conventions and permission model.
8. Proposed inventory entities and relationships.
9. Migration dependencies and integration risks.
10. Implementation phases and verification commands.

Do not assume that documentation accurately describes every current implementation detail.

Do not create duplicate organizations, vendors, accounts, audit tables, authentication systems, or journal engines.

If an essential architectural detail is uncertain, inspect further. If it cannot be established safely, document the uncertainty before making a consequential design decision.

## 3. Architectural principles

Use the existing stack and conventions. Where applicable, retain:

- Next.js App Router.
- React and TypeScript with strict typing.
- Tailwind CSS and the existing component library.
- Supabase Auth and PostgreSQL.
- Existing server-side authorization patterns.
- Existing organization and branch context.
- Ordered SQL migrations.
- Existing unit, integration, and end-to-end testing tools.

Prefer a modular monolith within the current application rather than introducing unnecessary microservices.

Organize inventory logic into clear boundaries:

- Domain: inventory rules, stock calculations, costing, and invariants.
- Application: receiving, issuing, transferring, adjusting, and approving transactions.
- Data access: authorized database queries and persistence.
- Presentation: routes, forms, dashboards, tables, and reports.
- Integration: accounting, vendors, fixed assets, audit logging, and notifications.

Follow existing repository boundaries instead of introducing a new architecture solely for stylistic reasons.

Keep important business rules out of UI components. Never rely on frontend validation alone to protect inventory or accounting invariants.

## 4. Inventory functional scope

Implement the following modules as a coherent inventory system.

### A. Inventory dashboard

Display organization-scoped metrics:

- Total active stock items.
- Total quantities on hand.
- Inventory valuation.
- Items below reorder level.
- Out-of-stock items.
- Pending purchase orders.
- Pending goods receipts.
- Pending approvals.
- Recent stock movements.
- Stock valuation trends where historical data supports them.

Provide date, branch, warehouse, category, and status filters where applicable.

Every KPI must come from real authorized data. Do not hardcode production figures or fabricate historical charts.

### B. Item and SKU master

Provide complete item lifecycle management.

Fields should include:

- Unique item code or SKU.
- Item name and description.
- Category and optional subcategory.
- Item type: stock item, non-stock item, consumable, or service.
- Base unit of measure.
- Purchase and issue units where supported.
- Unit conversion definitions where needed.
- Default purchase cost and selling price if relevant.
- Reorder level and optional maximum stock level.
- Preferred supplier linked to the existing vendor model.
- Inventory, expense/consumption, and cost-of-goods-sold account mappings where applicable.
- Active/inactive status.
- Optional barcode, manufacturer, brand, and image.
- Batch tracking, serial tracking, and expiry tracking options where required.

Enforce SKU uniqueness within the appropriate organization scope.

Prevent incompatible changes to items already referenced by posted transactions. Archive items instead of deleting historical records.

Do not treat a non-stock service as inventory merely because it appears on a purchase order.

### C. Categories and units of measure

Implement:

- Item categories and subcategories.
- Base units of measure.
- Purchase-to-base and issue-to-base conversions.
- Validation of conversion factors.
- Protection against invalid or incompatible conversions.

Use a consistent base quantity for stock calculations.

For fractional quantities, use PostgreSQL `numeric` with a documented precision and rounding policy. Do not use JavaScript floating-point arithmetic as the authoritative stock calculation.

### D. Warehouses and stock locations

Support:

- Multiple warehouses per organization.
- Warehouse code and name.
- Address and contact information where appropriate.
- Branch association.
- Active/inactive status.
- Optional internal bins or locations if required by the business.

Enforce organization boundaries on every warehouse relationship.

Do not assume that a warehouse and a branch are the same entity. A branch may have several warehouses, depending on the existing organizational model.

### E. Stock ledger and balances

Implement an authoritative, append-only stock movement ledger.

Each posted movement should record:

- Organization.
- Item and warehouse.
- Transaction type.
- Signed quantity delta.
- Unit cost and valuation delta when applicable.
- Source document type and ID.
- Transaction date and posting timestamp.
- Posting user.
- Reason or adjustment reference.
- Reversal reference, when applicable.
- Idempotency key or equivalent duplicate-posting protection.

The stock ledger is the source of truth for inventory movements.

Current balances may be maintained as transactional projections or derived from ledger entries, but they must reconcile to the ledger.

Do not allow users to edit posted ledger entries or directly overwrite stock balances.

Correct posted mistakes using controlled reversals and replacement transactions.

### F. Purchase orders

Build a purchasing workflow integrated with existing vendors:

Draft → Submit → Approve → Issue purchase order → Partially receive / Fully receive → Close or cancel according to valid business rules.

Support:

- Supplier selection.
- Purchase order number.
- Order and expected delivery dates.
- Item lines and units.
- Quantities and agreed unit prices.
- Applicable taxes, discounts, and charges.
- Line totals and document totals.
- Notes and attachments where supported.
- Approval history.
- Outstanding quantities and receipt history.

Prevent duplicate submissions and invalid state transitions.

Do not create duplicate supplier records.

Purchase orders alone must not increase physical stock or automatically post inventory journals.

### G. Goods received notes (GRN)

Implement controlled receipt of goods against an approved purchase order.

Support:

- Receipt number.
- Supplier and purchase order reference.
- Receiving warehouse.
- Actual quantities received.
- Partial deliveries.
- Accepted and rejected quantities where required.
- Receipt date and reference documents.
- Lot, serial, or expiry details for tracked items.
- Receiving user and approval status.

On successful posting, update stock through the stock ledger within the appropriate atomic database transaction.

Prevent over-receiving unless an explicit, authorized tolerance policy permits it.

Ensure repeated requests cannot receive the same quantities twice.

Keep physical receipt separate from supplier invoicing and accounts-payable recognition.

### H. Stock issues and consumption

Support authorized issues for:

- Employee or department consumption.
- Operational expenses.
- Maintenance and facilities.
- Project or cost-centre usage where the existing accounting model supports it.
- Approved returns to inventory.

Capture requester, department, cost centre, receiving party, issue reason, warehouse, item lines, quantities, approval, and posting status as appropriate.

An issue reduces inventory only when posted successfully.

Where an issue is an expense, use the appropriate expense account and accounting integration. Do not confuse employee reimbursement, payroll deduction, and inventory consumption.

### I. Inter-warehouse transfers

Implement:

- Source and destination warehouses.
- Item and quantity lines.
- Transfer request and approval.
- Dispatch and receipt confirmation.
- Partial receipt and discrepancy handling if required.
- Transfer references and movement history.

Transfers between warehouses belonging to the same organization must preserve the organization's total inventory quantity and value, apart from explicitly documented loss or discrepancy events.

Prevent negative stock at the source when the configured policy disallows it.

Never allow a transfer to cross organization boundaries.

For systems requiring dispatch-to-receipt tracking, model in-transit stock explicitly rather than silently reducing one warehouse and increasing another at unrelated times.

### J. Stock adjustments and stocktakes

Implement controlled adjustments for:

- Damage.
- Expiry.
- Loss.
- Found stock.
- Data correction.
- Approved write-offs.

Provide:

- Reason codes.
- Supporting notes and evidence where supported.
- Before-and-after quantities.
- Expected and counted quantities.
- Variance calculations.
- Approval workflow.
- Audit history.

Support stocktake sessions with snapshot or cutoff-aware counting semantics.

Avoid overwriting transactions posted after a count began. Resolve concurrent movements using a defined cutoff, reconciliation, or variance-posting policy.

High-value or material adjustments should require elevated authorization according to configurable approval rules.

### K. Reorder management

Calculate reorder alerts from real stock data.

Consider:

- Available stock.
- Reserved stock if reservations exist.
- Reorder level.
- Open purchase-order quantities.
- Outstanding receipts.
- Lead time if maintained.

Do not automatically generate purchase orders unless an explicit configured workflow requires it.

Provide reorder suggestions with recommended quantities and a clear explanation of the calculation.

### L. Inventory reports

Implement:

- Stock on hand by item and warehouse.
- Inventory valuation.
- Stock movement history.
- Receipts and issues.
- Transfer history.
- Adjustment and variance report.
- Low-stock and out-of-stock report.
- Expiring and expired lots where lot tracking is enabled.
- Item transaction history.
- Purchase-order outstanding quantities.
- Inventory-to-general-ledger reconciliation.

Reports must respect organization, branch, warehouse, permissions, and date filters.

Use existing export and print utilities. If CSV, spreadsheet, or PDF export is available elsewhere in the application, reuse the established approach.

Clearly identify report generation timestamps, applied filters, and the valuation basis.

## 5. Inventory costing and accounting

Treat inventory valuation as a financial control, not a display-only feature.

### Costing policy

Inspect the existing accounting implementation before selecting a method.

If no policy exists, propose weighted-average costing as the initial default, document the decision, and obtain any necessary business approval before implementing production posting behavior.

Keep costing logic isolated, deterministic, and unit tested.

Support purchase-cost allocation for relevant landed costs only when the business requires it and the required source data is available.

Define how returns, write-offs, negative stock, backdated transactions, and reversals affect valuation.

Do not silently recalculate historical posted valuation when a later receipt changes the average cost. Preserve historical transaction values and use a documented adjustment or recalculation policy.

### Accounting integration

Reuse the existing chart of accounts, journal-posting functions, general ledger, fiscal-period controls, and audit infrastructure.

Map accounts using the application's established account model, with appropriate organization ownership and validation.

Typical accounting events, subject to the existing accounting policy:

1. Inventory purchase receipt:
   - Debit inventory asset.
   - Credit goods-received-not-invoiced or another approved receipt-clearing account, if the accounting model supports accrual-based receiving.

2. Supplier invoice:
   - Debit the appropriate inventory asset, clearing account, expense, or other relevant account.
   - Credit accounts payable.
   - Account for applicable tax and purchase-price differences according to the established accounting rules.

3. Inventory consumption:
   - Debit the relevant expense, cost centre, project, or cost-of-goods-sold account.
   - Credit inventory asset.

4. Inventory write-off:
   - Debit the appropriate loss or expense account.
   - Credit inventory asset.

5. Approved stock gain:
   - Debit inventory asset.
   - Credit the approved adjustment or gain account.

6. Inter-warehouse transfer:
   - Preserve total organization inventory value.
   - Do not generate a profit or loss merely because stock moved between warehouses.

These are accounting patterns, not permission to create a second journal engine. Follow the actual existing posting contracts and accounting policies.

Each financial event must:

- Post to the correct organization and accounting period.
- Use balanced journal entries.
- Be idempotent.
- Maintain a traceable link to its source transaction.
- Avoid duplicate posting under retries or concurrent requests.
- Respect closed-period rules.
- Record the resulting journal reference.
- Support controlled reversal.

Do not silently post unbalanced journals or invent account IDs.

Where required account mappings or financial policies are missing, fail safely and explain what must be configured.

## 6. Database design and migrations

Design normalized tables that match the existing naming conventions.

Potential entities include:

- inventory_categories
- inventory_units
- inventory_items
- inventory_item_units
- inventory_warehouses
- inventory_stock_movements
- inventory_stock_balances
- inventory_purchase_orders
- inventory_purchase_order_lines
- inventory_goods_receipts
- inventory_goods_receipt_lines
- inventory_issues
- inventory_issue_lines
- inventory_transfers
- inventory_transfer_lines
- inventory_adjustments
- inventory_adjustment_lines
- inventory_stocktakes
- inventory_stocktake_lines
- inventory_lots
- inventory_serial_numbers, if serial tracking is required
- inventory_approvals, only if existing approval infrastructure cannot be reused

These are proposed names, not a mandate to duplicate existing entities.

Use existing vendors, departments, branches, users, accounts, and audit tables wherever possible.

### Database safeguards

- Add organization ownership to all applicable records.
- Use foreign keys, unique constraints, check constraints, and appropriate indexes.
- Add organization-scoped uniqueness where needed.
- Enforce valid document state transitions.
- Prevent duplicate posting with unique source references or idempotency constraints.
- Protect balances from race conditions.
- Use database transactions for multi-row posting operations.
- Use row locks, conditional updates, or equivalent concurrency-safe techniques.
- Prevent unauthorized cross-tenant relationships.
- Add suitable indexes for common organization, warehouse, item, date, status, and source-document queries.

Use ordered, forward-only migrations consistent with the repository.

Never edit an already deployed migration to retrofit a feature.

Never drop existing production tables or reset a shared database as part of implementation.

Provide a rollback or recovery plan where safe rollback of data-changing migrations is not possible.

## 7. Supabase security and authorization

Apply both server-side authorization and PostgreSQL Row-Level Security wherever appropriate.

Reuse the current organization membership and role system.

Define least-privilege capabilities for:

- Inventory viewing.
- Item and warehouse management.
- Purchase-order creation.
- Purchase-order approval.
- Goods receipt.
- Stock issue.
- Transfer dispatch and receipt.
- Stock adjustment.
- Stocktake management.
- Inventory valuation and financial reports.
- Inventory configuration.
- Accounting posting and reversal.

Map these capabilities to existing roles only after inspecting the actual role definitions and permission helpers.

Do not assume that all administrators, accountants, HR managers, and employees should have identical inventory permissions.

### Security requirements

- Never trust organization IDs supplied by the client.
- Derive or validate organization context using the existing trusted server-side pattern.
- Apply RLS policies to all organization-owned tables.
- Validate access to related records, not just the parent record.
- Do not expose service-role credentials to the browser.
- Do not allow the client to write directly to authoritative stock balances or posted movements.
- Keep sensitive audit information and financial operations protected.
- Test that one organization cannot access another organization's inventory.
- Ensure unauthorized users cannot approve, post, or reverse inventory transactions by invoking server actions or APIs directly.

Use the repository's established server-side Supabase client and mutation patterns.

## 8. User interface and navigation

Follow the existing Plutus design system rather than introducing a visually unrelated application.

Add an Inventory navigation group using the established sidebar and route conventions.

Suggested navigation:

- Overview
- Items
- Categories
- Warehouses
- Stock Movements
- Purchase Orders
- Goods Receipts
- Stock Issues
- Transfers
- Stocktakes
- Adjustments
- Reorder Management
- Reports
- Inventory Settings

Show only the appropriate navigation items and actions for the current user's permissions.

### UI requirements

- Consistent typography, spacing, colors, and component behavior.
- Responsive desktop, tablet, and mobile layouts.
- Searchable and filterable data tables.
- Pagination or established server-side data loading.
- Validated forms with helpful error messages.
- Loading, empty, error, and success states.
- Confirmation dialogs for consequential actions.
- Clear draft, pending, approved, posted, rejected, and reversed states.
- Accessible labels, keyboard navigation, and focus management.
- Currency and quantity formatting consistent with existing localization.
- Explicit confirmation before irreversible or high-impact actions.
- Useful transaction detail pages with document history and linked records.

Do not use decorative dashboards that conceal missing functionality.

Do not add nonfunctional buttons, fake charts, hardcoded metrics, or mock records to production workflows.

Reuse existing UI primitives and avoid unnecessary dependencies.

## 9. Business rules and invariants

The following rules are mandatory unless an explicitly approved existing business policy requires a documented alternative.

1. Posted stock movements are immutable.
2. Stock quantities change only through authorized, traceable transactions.
3. Draft documents do not affect posted stock.
4. A successful posting cannot be duplicated by a retry.
5. Concurrent transactions cannot silently overspend the same available stock.
6. Negative stock is rejected by default unless an explicitly configured policy permits it.
7. Warehouse transfers preserve total inventory value.
8. Posted accounting journals are balanced and traceable.
9. Reversals reference the original transaction and cannot be duplicated.
10. Closed accounting periods cannot be bypassed.
11. Historical transactions remain accessible after an item is archived.
12. Tenant isolation applies to every transaction and relationship.
13. Item, unit, warehouse, and account references must belong to the correct organization.
14. Partial receipts and partial issues cannot exceed authorized remaining quantities without an explicit policy.
15. A failed financial posting must not leave stock and accounting in inconsistent states.
16. Every material inventory action must be auditable.
17. Stocktakes must reconcile against the correct count baseline and subsequent movements.
18. Backdated transactions must follow an explicit costing and accounting-period policy.

Where stock and accounting data are stored in the same PostgreSQL database, prefer a single atomic database transaction for the stock movement, valuation update, journal posting, and source-document status transition.

If the existing architecture requires asynchronous posting, implement an explicit durable outbox or equivalent reconciliation mechanism with idempotent processing. Do not simulate atomicity with independent client-side requests.

## 10. Testing requirements

Use the testing tools already configured in the repository.

### Unit tests

Cover:

- Unit conversions.
- Quantity validation.
- Weighted-average costing or the approved costing method.
- Reorder calculations.
- Partial receipts.
- Issue validation.
- Transfer valuation.
- Stocktake variances.
- Adjustment calculations.
- Journal construction and balance validation.
- Reversal calculations.
- Rounding and numeric precision.

### Integration tests

Cover:

- Database migrations replay from a clean database.
- Item and warehouse creation.
- Purchase-order approval.
- Goods receipt and stock balance updates.
- Stock issue and stock balance reduction.
- Inter-warehouse transfers.
- Partial delivery and remaining quantity calculations.
- Adjustment approval and posting.
- Inventory-to-general-ledger reconciliation.
- Duplicate request protection.
- Concurrent issues against limited stock.
- Concurrent receipt and transfer operations.
- Failed posting rollback.
- Closed-period rejection.
- Organization isolation and RLS enforcement.

### End-to-end tests

Cover the principal workflows:

1. Create an item and warehouse.
2. Create and approve a purchase order.
3. Receive stock.
4. Verify the stock balance and movement history.
5. Issue stock for consumption.
6. Verify stock valuation and accounting entries.
7. Transfer stock between warehouses.
8. Complete a stocktake and approve an adjustment.
9. Export an inventory report.
10. Verify restricted users cannot perform unauthorized actions.

Use isolated test organizations and seeded test data. Never run destructive integration tests against a production database.

## 11. Implementation phases

Implement the system in controlled, reviewable phases.

### Phase 0 — Discovery and design

- Inspect the codebase.
- Document the architecture.
- Identify reusable entities and accounting contracts.
- Define inventory boundaries and unresolved policy decisions.
- Create an implementation plan.

Do not begin large-scale code generation before completing discovery.

### Phase 1 — Inventory foundation

- Database migrations.
- Item categories and item master.
- Units of measure.
- Warehouses and permissions.
- Stock ledger and balance model.
- Audit integration.
- Basic inventory dashboard.

Deliver working, tested foundations.

### Phase 2 — Operational transactions

- Purchase orders.
- Goods receipts.
- Stock issues.
- Inter-warehouse transfers.
- Adjustments and reversals.
- Approval and document history.

Ensure concurrency safety and idempotency.

### Phase 3 — Costing and accounting

- Implement the approved costing method.
- Connect inventory events to existing journal-posting functions.
- Integrate account mappings and fiscal-period validation.
- Add valuation and ledger reconciliation.
- Test financial consistency and recovery behavior.

Do not silently bypass this phase in order to make the UI appear complete.

### Phase 4 — Stock control and reporting

- Stocktakes.
- Reorder alerts.
- Lot and expiry tracking where required.
- Inventory reports and exports.
- Advanced filters and drill-downs.

### Phase 5 — Hardening and release

- Security and RLS verification.
- Accessibility and responsive UI checks.
- Performance checks.
- Migration replay.
- Full regression suite.
- Production build.
- Deployment and recovery documentation.

At the end of each phase, summarize changes, test results, known limitations, and the next phase.

## 12. Implementation workflow

For each phase:

1. Inspect relevant existing code.
2. Identify the smallest coherent set of changes.
3. Write down data invariants and authorization requirements.
4. Add the required migration and tests.
5. Implement domain and server-side logic.
6. Implement the UI and navigation.
7. Run targeted tests and type checking.
8. Run lint and the relevant production build when practical.
9. Inspect the diff for regressions and accidental unrelated changes.
10. Update architecture and feature documentation.

Use existing scripts discovered from the repository. Do not invent package commands.

Do not overwrite unrelated uncommitted user changes. Inspect Git status before modifying files.

Do not automatically commit, push, deploy, reset databases, or apply destructive migrations without explicit authorization.

If an external service, environment variable, account mapping, or business decision is missing, document the dependency and implement only the safe parts that can be completed.

## 13. Definition of done

The inventory subsystem is not complete until:

- Its modules are accessible through the existing navigation and permissions.
- Database migrations apply cleanly in order.
- Item, warehouse, and transaction workflows persist real data.
- Every stock change is represented by a traceable ledger movement.
- Concurrent requests and retries cannot corrupt stock.
- Inventory valuation follows the approved costing policy.
- Financial postings use the existing accounting infrastructure.
- Stock and accounting remain consistent after errors and reversals.
- RLS and server-side authorization prevent cross-organization access.
- Reports reconcile to the underlying ledger.
- Unit, integration, and regression tests pass.
- Existing HR, payroll, and accounting features continue to work.
- Documentation explains configuration, permissions, workflows, accounting behavior, and recovery.

## 14. Final delivery report

When implementation is complete, report:

1. Modules implemented and their routes.
2. Database migrations added.
3. Existing systems reused and integration points.
4. Permissions and RLS policies added or extended.
5. Stock valuation method and assumptions.
6. Accounting events and journal mappings.
7. Tests executed and their actual outcomes.
8. Build and lint results.
9. Remaining limitations and business decisions.
10. Deployment, migration, and rollback/recovery steps.

Distinguish verified results from unexecuted checks. Never claim a feature, migration, or test is complete unless it has actually been implemented and verified.
