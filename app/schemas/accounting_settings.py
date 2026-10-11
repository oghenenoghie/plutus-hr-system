import uuid
from datetime import datetime

from pydantic import BaseModel


class AccountingSettingsOut(BaseModel):
    post_statutory_remittances: bool
    updated_at: datetime | None
    updated_by: uuid.UUID | None

    model_config = {"from_attributes": True}


class AccountingSettingsUpdate(BaseModel):
    # When true, marking a statutory liability remitted also posts
    # Dr <scheme>_payable / Cr cash, going forward only. Switching it on
    # first seeds the default chart of accounts if the org has none.
    post_statutory_remittances: bool | None = None
