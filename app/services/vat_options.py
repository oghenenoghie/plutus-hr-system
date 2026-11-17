"""What the VAT dropdown on an invoice or a vendor bill offers."""

import uuid

from sqlalchemy.orm import Session

from app.domain.accounting.vat import (
    TREATMENT_LABELS,
    VatTreatment,
    percent_label,
    standard_vat_rate_ppm,
)
from app.schemas.invoices import VatOptionOut, VatOptionsOut
from app.services.jurisdiction import organisation_country
from app.services.posting import today_lagos


def vat_options(db: Session, org_id: uuid.UUID) -> VatOptionsOut:
    """The organisation's standard rate (when one is on record for its
    country), exempt, zero-rated, and a rate the user names."""
    country = organisation_country(db, org_id)
    options = []
    standard = standard_vat_rate_ppm(country, today_lagos())
    if standard is not None:
        options.append(
            VatOptionOut(
                treatment=VatTreatment.STANDARD,
                label=f"{TREATMENT_LABELS[VatTreatment.STANDARD]} {percent_label(standard)}",
                rate_ppm=standard,
            )
        )
    for treatment in (VatTreatment.EXEMPT, VatTreatment.ZERO_RATED):
        options.append(
            VatOptionOut(treatment=treatment, label=TREATMENT_LABELS[treatment], rate_ppm=0)
        )
    options.append(VatOptionOut(treatment=VatTreatment.OTHER, label="Other rate", rate_ppm=None))
    return VatOptionsOut(country_code=country, options=options)
