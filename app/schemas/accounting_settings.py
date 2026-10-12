import uuid
from datetime import date, datetime

from pydantic import BaseModel


class AccountingSettingsOut(BaseModel):
    post_statutory_remittances: bool
    lock_date: date | None
    updated_at: datetime | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class AccountingSettingsUpdate(BaseModel):
    # When true, marking a statutory liability remitted also posts
    # Dr <scheme>_payable / Cr cash, going forward only. Switching it on
    # first seeds the default chart of accounts if the org has none.
    post_statutory_remittances: bool | None = None
    # D13: nothing may be posted on or before this day. Send null to clear
    # it; it can't be in the future.
    lock_date: date | None = None
