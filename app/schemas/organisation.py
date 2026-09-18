import uuid

from pydantic import BaseModel, EmailStr, Field

from app.domain.payroll.frequency import PayFrequency


class OrganisationOut(BaseModel):
    id: uuid.UUID
    name: str
    rc_number: str | None
    company_tin: str | None
    default_pay_frequency: PayFrequency
    default_pfa: str | None
    states_of_operation: list[str]

    model_config = {"from_attributes": True}


class OrganisationUpdate(BaseModel):
    name: str | None = None
    rc_number: str | None = None
    company_tin: str | None = None
    default_pay_frequency: PayFrequency | None = None
    default_pfa: str | None = None
    states_of_operation: list[str] | None = None


class OrganisationSignupRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=255)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)


class OrganisationSignupOut(BaseModel):
    org_id: uuid.UUID
    account_id: uuid.UUID
    email: str

    model_config = {"from_attributes": True}
