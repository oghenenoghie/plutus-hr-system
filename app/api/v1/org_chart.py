from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_tenant_db
from app.core.security import TokenClaims
from app.domain.org_chart import OrgChartEmployee, OrgChartTreeNode, build_org_chart
from app.models.employee import Employee
from app.schemas.org_chart import OrgChartNode

router = APIRouter(tags=["org-chart"])


def _to_out(node: OrgChartTreeNode) -> OrgChartNode:
    return OrgChartNode(
        employee_id=node.employee.id,
        full_name=node.employee.full_name,
        job_title=node.employee.job_title,
        department_id=node.employee.department_id,
        reports=[_to_out(report) for report in node.reports],
    )


@router.get("/org-chart", response_model=list[OrgChartNode])
def get_org_chart(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(get_current_claims)
) -> list[OrgChartNode]:
    rows = db.execute(
        select(
            Employee.id,
            Employee.full_name,
            Employee.job_title,
            Employee.department_id,
            Employee.manager_id,
        )
    ).all()
    employees = [
        OrgChartEmployee(
            id=row.id,
            full_name=row.full_name,
            job_title=row.job_title,
            department_id=row.department_id,
            manager_id=row.manager_id,
        )
        for row in rows
    ]
    return [_to_out(node) for node in build_org_chart(employees)]
