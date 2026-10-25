import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.db import tenant_session
from app.models.ledger import LedgerEntry
from app.models.membership import Membership, Role
from app.models.organisation import Organisation
from app.models.pay_run import PayRun
from app.services.accounting_settings import update_accounting_settings
from app.services.jurisdiction import require_catalogued_country
from app.services.memberships import create_membership


def signup_organisation(
    *,
    org_name: str,
    admin_email: str,
    admin_password: str,
    org_address: str | None = None,
    country_code: str = "NG",
) -> tuple[Organisation, Membership]:
    """The only way a brand-new company gets onto Plutus — there's no
    invite-only path in for a first org, unlike every subsequent login
    within it (see MembershipCreate's own docstring). Opens its own
    tenant_session rather than taking a Session/claims dependency, since
    by definition no org or account exists yet to derive either from —
    same reasoning as create_org() in the test helpers, which this
    mirrors: the org_id is generated client-side so the RLS
    WITH CHECK (id = current_org GUC) is satisfiable on first insert.
    """
    country_code = require_catalogued_country(country_code).code
    org_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), Role.ADMIN.value) as db:
        org = Organisation(id=org_id, name=org_name, address=org_address, country_code=country_code)
        db.add(org)
        db.flush()
        membership = create_membership(
            db, org_id=org_id, email=admin_email, password=admin_password, role=Role.ADMIN
        )
        # A brand-new org has no history to double-count (audit A8), so it
        # starts with remittance posting on; enabling also seeds the chart.
        update_accounting_settings(
            db, org_id=org_id, actor_account_id=None, post_statutory_remittances=True
        )
    return org, membership


def get_organisation(db: Session, org_id: uuid.UUID) -> Organisation:
    org = db.get(Organisation, org_id)
    if org is None:
        raise ValueError("organisation not found")
    return org


class CountryChangeError(ValueError):
    """The organisation already has payroll or accounting history in its
    current country's rules and currency."""


def update_organisation(db: Session, org: Organisation, **fields: object) -> Organisation:
    country_code = fields.pop("country_code", None)
    if isinstance(country_code, str):
        _change_country(db, org, country_code)
    for field, value in fields.items():
        if value is not None:
            setattr(org, field, value)
    db.flush()
    return org


def _change_country(db: Session, org: Organisation, country_code: str) -> None:
    """Posted payslips, liabilities and journals keep the rules and currency
    they were made under, so the country can only change before there are
    any; after that it takes a migration, not a setting."""
    country_code = require_catalogued_country(country_code).code
    if country_code == org.country_code:
        return
    # Every journal has ledger lines, and bills, invoices and manual
    # journals post lines without a journal header, so the lines are what
    # count.
    has_history = db.scalar(
        select(
            exists().where(PayRun.org_id == org.id) | exists().where(LedgerEntry.org_id == org.id)
        )
    )
    if has_history:
        raise CountryChangeError(
            "The country can't change once the organisation has a pay run or a posted journal."
        )
    org.country_code = country_code
