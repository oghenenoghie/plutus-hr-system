import uuid

from pydantic import BaseModel


class OrgChartNode(BaseModel):
    employee_id: uuid.UUID
    full_name: str
    job_title: str | None
    department_id: uuid.UUID | None
    reports: list["OrgChartNode"]


OrgChartNode.model_rebuild()
