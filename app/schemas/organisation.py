import uuid

from pydantic import BaseModel, EmailStr, Field, computed_field

from app.compliance.multicountry import TaxStatus, get_country_profile
from app.domain.payroll.frequency import PayFrequency


class OrganisationOut(BaseModel):
    id: uuid.UUID
    name: str
    rc_number: str | None
    company_tin: str | None
    address: str | None
    default_pay_frequency: PayFrequency
    default_pfa: str | None
    states_of_operation: list[str]
    country_code: str

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def country_name(self) -> str:
        return get_country_profile(self.country_code).name

    @computed_field  # type: ignore[prop-decorator]
    @property
    def currency(self) -> str:
        return get_country_profile(self.country_code).currency


class OrganisationUpdate(BaseModel):
    name: str | None = None
    rc_number: str | None = None
    company_tin: str | None = None
    address: str | None = Field(default=None, max_length=500)
    default_pay_frequency: PayFrequency | None = None
    default_pfa: str | None = None
    states_of_operation: list[str] | None = None
    # Only to a country whose rules are approved, and only while the
    # organisation has no pay run and no posted journal.
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")


class OrganisationSignupRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=255)
    org_address: str | None = Field(default=None, max_length=500)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)
    country_code: str = Field(default="NG", pattern=r"^[A-Za-z]{2}$")


class OrganisationSignupOut(BaseModel):
    org_id: uuid.UUID
    account_id: uuid.UUID
    email: str

    model_config = {"from_attributes": True}


class SignupCountryOut(BaseModel):
    """A catalogued country as the sign-up form offers it. Every one can be
    chosen (selectable); payroll_available says whether payroll and
    statutory tax can run there yet."""

    code: str
    name: str
    currency: str
    status: TaxStatus
    selectable: bool
    payroll_available: bool
