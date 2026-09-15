import uuid

from pydantic import BaseModel

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
