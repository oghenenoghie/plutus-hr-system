import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

from app.domain.nuban import NIGERIAN_BANKS, is_valid_nuban


class BankAccountInput(BaseModel):
    bank_name: str
    account_number: str
    account_name: str

    @field_validator("account_number")
    @classmethod
    def _digits_only(cls, value: str) -> str:
        if len(value) != 10 or not value.isdigit():
            raise ValueError("account_number must be exactly 10 digits")
        return value

    @model_validator(mode="after")
    def _check_nuban(self) -> "BankAccountInput":
        """Only a bank on the curated list gets checksum-validated — an
        unlisted bank still needs the 10-digit format above, just not the
        checksum, since there's no known bank code to validate against."""
        bank_code = NIGERIAN_BANKS.get(self.bank_name)
        if bank_code is not None and not is_valid_nuban(bank_code, self.account_number):
            raise ValueError(
                f"'{self.account_number}' is not a valid account number for {self.bank_name} "
                "— check digit mismatch"
            )
        return self


class BankAccountOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    bank_name: str
    account_number: str
    account_name: str
    verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}
