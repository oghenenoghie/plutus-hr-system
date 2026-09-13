import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class OrgChartEmployee:
    id: uuid.UUID
    full_name: str
    job_title: str | None
    department_id: uuid.UUID | None
    manager_id: uuid.UUID | None


@dataclass(frozen=True)
class OrgChartTreeNode:
    employee: OrgChartEmployee
    reports: tuple["OrgChartTreeNode", ...]


def build_org_chart(employees: list[OrgChartEmployee]) -> tuple[OrgChartTreeNode, ...]:
    """Builds a forest (not always a single tree — an org can have several
    top-level employees with no manager) from a flat employee list.
    Defensive against a manager_id cycle in the data (nothing in the schema
    actually prevents one): each employee is placed at most once, under
    whichever branch reaches it first in manager_id-chases-up order.
    """
    by_manager: dict[uuid.UUID | None, list[OrgChartEmployee]] = {}
    for employee in employees:
        by_manager.setdefault(employee.manager_id, []).append(employee)

    visited: set[uuid.UUID] = set()

    def _build(manager_id: uuid.UUID | None) -> tuple[OrgChartTreeNode, ...]:
        nodes = []
        for employee in by_manager.get(manager_id, []):
            if employee.id in visited:
                continue
            visited.add(employee.id)
            nodes.append(OrgChartTreeNode(employee=employee, reports=_build(employee.id)))
        return tuple(nodes)

    return _build(None)
