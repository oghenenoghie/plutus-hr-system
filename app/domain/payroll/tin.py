class MissingTinError(Exception):
    """A payroll run must not proceed for an employee with no valid Tax
    Identification Number — a hard pre-run gate, never a warning that lets
    the run continue silently (nigeria-statutory-compliance.md §1)."""


def ensure_tin_present(tin: str | None) -> None:
    if not tin or not tin.strip():
        raise MissingTinError("employee has no valid TIN; payroll run must not proceed")
