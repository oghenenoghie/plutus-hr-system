import uuid
from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from app.domain.accounting.numbering import CATEGORY_LABELS, AccountCategory
from app.models.chart_account import AccountType


class ChartAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: AccountType
    # Where the account is reported; defaults to the usual place for its type
    # (an expense is an overhead unless it's put under cost of sales).
    category: AccountCategory | None = None
    # Four digits in the category's range; the next free one when left out.
    account_number: str | None = Field(default=None, max_length=20)
    # The key ledger lines post to; made from the number when left out.
    code: str | None = Field(default=None, max_length=64)


class ChartAccountUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class ChartAccountOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    code: str
    account_number: str
    category: AccountCategory
    name: str
    type: AccountType
    is_system: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS[self.category]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def statement(self) -> str:
        """Which statement the account is reported on."""
        if self.type in (AccountType.REVENUE, AccountType.EXPENSE):
            return "profit_and_loss"
        return "balance_sheet"


class NextAccountNumberOut(BaseModel):
    category: AccountCategory
    account_number: str
    range_from: int
    range_to: int
