from pydantic import BaseModel


class RemindersSummaryOut(BaseModel):
    deadline_count: int
    stale_approval_count: int
    notifications_created: int
