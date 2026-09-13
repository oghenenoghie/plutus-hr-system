import uuid
from datetime import datetime

from pydantic import BaseModel


class TrainingCourseAttachmentCreate(BaseModel):
    title: str
    storage_url: str


class TrainingCourseAttachmentOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    course_id: uuid.UUID
    title: str
    storage_url: str
    created_at: datetime

    model_config = {"from_attributes": True}
