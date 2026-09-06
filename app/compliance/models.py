import enum
from datetime import date

from pydantic import BaseModel, ConfigDict


class BorneBy(str, enum.Enum):
    EMPLOYEE = "employee"
    EMPLOYER = "employer"
    BOTH = "both"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Band(Frozen):
    up_to_minor: int | None  # cumulative ceiling for this band; None = top open band
    rate_ppm: int  # parts-per-million, e.g. 15% -> 150_000


class PayeRule(Frozen):
    bands: tuple[Band, ...]
    tax_free_threshold_minor: int
    rent_relief_rate_ppm: int
    rent_relief_cap_minor: int
    authority: str = "STATE_IRS"
    due_day_of_following_month: int = 10


class PensionRule(Frozen):
    employee_rate_ppm: int
    employer_rate_ppm: int
    borne_by: BorneBy = BorneBy.BOTH
    authority: str = "PFA"
    due_working_days_after_payment: int = 7


class NhfRule(Frozen):
    rate_ppm: int
    borne_by: BorneBy = BorneBy.EMPLOYEE
    authority: str = "FMBN"
    due_days_after_payment: int = 30


class NsitfRule(Frozen):
    rate_ppm: int
    borne_by: BorneBy = BorneBy.EMPLOYER
    authority: str = "NSITF"
    due_day_of_following_month: int = 16


class ItfRule(Frozen):
    """The headcount/turnover qualification test is unconfirmed against a
    primary source as of this rule version (nigeria-statutory-compliance.md
    §7) — deliberately not modelled here. Callers must decide `qualifies`
    themselves; this engine never guesses who owes ITF.
    """

    rate_ppm: int
    borne_by: BorneBy = BorneBy.EMPLOYER
    authority: str = "ITF"
    due_month: int = 4
    due_day: int = 1


class WhtCategoryRule(Frozen):
    category: str
    rate_ppm: int


class WhtRule(Frozen):
    categories: tuple[WhtCategoryRule, ...]
    authority: str = "NRS"
    due_day_of_following_month: int = 21

    def rate_for(self, category: str) -> int:
        for entry in self.categories:
            if entry.category == category:
                return entry.rate_ppm
        raise ValueError(f"no WHT rate configured for category {category!r}")


class RuleVersion(Frozen):
    """NHIS/NHIA is deliberately absent: the reference (§5) is explicit that
    the rate varies by scheme and there is no single national figure to
    encode without inventing one. A calculator arrives once a specific
    scheme's rate is confirmed against a primary source.
    """

    id: str
    country: str
    effective_from: date
    effective_to: date | None
    paye: PayeRule
    pension: PensionRule
    nhf: NhfRule
    nsitf: NsitfRule
    itf: ItfRule
    wht: WhtRule
