import uuid

from app.domain.org_chart import OrgChartEmployee, build_org_chart


def _employee(name: str, manager_id: uuid.UUID | None = None) -> OrgChartEmployee:
    return OrgChartEmployee(
        id=uuid.uuid4(), full_name=name, job_title=None, department_id=None, manager_id=manager_id
    )


def test_builds_a_tree_from_manager_chains() -> None:
    ceo = _employee("CEO")
    vp = _employee("VP", manager_id=ceo.id)
    ic = _employee("IC", manager_id=vp.id)

    forest = build_org_chart([ic, ceo, vp])

    assert len(forest) == 1
    assert forest[0].employee.full_name == "CEO"
    assert len(forest[0].reports) == 1
    assert forest[0].reports[0].employee.full_name == "VP"
    assert forest[0].reports[0].reports[0].employee.full_name == "IC"


def test_multiple_employees_with_no_manager_are_separate_roots() -> None:
    a = _employee("A")
    b = _employee("B")

    forest = build_org_chart([a, b])

    assert {node.employee.full_name for node in forest} == {"A", "B"}


def test_a_manager_cycle_does_not_infinite_loop_and_is_excluded() -> None:
    a = _employee("A")
    b = _employee("B")
    # Rebuild with a mutual cycle: A's manager is B, B's manager is A.
    a = OrgChartEmployee(a.id, a.full_name, a.job_title, a.department_id, manager_id=b.id)
    b = OrgChartEmployee(b.id, b.full_name, b.job_title, b.department_id, manager_id=a.id)

    forest = build_org_chart([a, b])

    assert forest == ()
