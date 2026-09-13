from fastapi import FastAPI, Request
from fastapi.responses import Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.api_keys import router as api_keys_router
from app.api.v1.audit_log import router as audit_log_router
from app.api.v1.auth import router as auth_router
from app.api.v1.benefits import router as benefits_router
from app.api.v1.bills import router as bills_router
from app.api.v1.branches import router as branches_router
from app.api.v1.budgets import router as budgets_router
from app.api.v1.candidates import router as candidates_router
from app.api.v1.chart_accounts import router as chart_accounts_router
from app.api.v1.company_assets import router as company_assets_router
from app.api.v1.contractors import router as contractors_router
from app.api.v1.customers import router as customers_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.departments import router as departments_router
from app.api.v1.disciplinary_cases import router as disciplinary_cases_router
from app.api.v1.employees import router as employees_router
from app.api.v1.expenses import router as expenses_router
from app.api.v1.final_settlement import router as final_settlement_router
from app.api.v1.financial_statements import router as financial_statements_router
from app.api.v1.fixed_assets import router as fixed_assets_router
from app.api.v1.general_ledger import router as general_ledger_router
from app.api.v1.health import router as health_router
from app.api.v1.invoices import router as invoices_router
from app.api.v1.job_grades import router as job_grades_router
from app.api.v1.job_postings import router as job_postings_router
from app.api.v1.leave import router as leave_router
from app.api.v1.leave_encashment import router as leave_encashment_router
from app.api.v1.loans import router as loans_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.overtime import router as overtime_router
from app.api.v1.pay_runs import router as pay_runs_router
from app.api.v1.performance_reviews import router as performance_reviews_router
from app.api.v1.policies import router as policies_router
from app.api.v1.reports import router as reports_router
from app.api.v1.shifts import router as shifts_router
from app.api.v1.simulation import router as simulation_router
from app.api.v1.statutory_liabilities import router as statutory_liabilities_router
from app.api.v1.training_courses import router as training_courses_router
from app.api.v1.training_enrollments import router as training_enrollments_router
from app.api.v1.union_memberships import router as union_memberships_router
from app.api.v1.vendors import router as vendors_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware
from app.core.rate_limit import limiter


def _handle_rate_limit_exceeded(request: Request, exc: Exception) -> Response:
    # Starlette's add_exception_handler wants a Callable[[Request, Exception],
    # Response]; slowapi's own handler is typed against the concrete
    # RateLimitExceeded it's only ever registered for. This is always that
    # exception in practice — add_exception_handler only calls the handler
    # it was registered against — so the narrowing is safe.
    assert isinstance(exc, RateLimitExceeded)
    return _rate_limit_exceeded_handler(request, exc)


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _handle_rate_limit_exceeded)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(employees_router, prefix="/api/v1")
    app.include_router(pay_runs_router, prefix="/api/v1")
    app.include_router(loans_router, prefix="/api/v1")
    app.include_router(leave_router, prefix="/api/v1")
    app.include_router(final_settlement_router, prefix="/api/v1")
    app.include_router(statutory_liabilities_router, prefix="/api/v1")
    app.include_router(simulation_router, prefix="/api/v1")
    app.include_router(expenses_router, prefix="/api/v1")
    app.include_router(benefits_router, prefix="/api/v1")
    app.include_router(dashboard_router, prefix="/api/v1")
    app.include_router(contractors_router, prefix="/api/v1")
    app.include_router(audit_log_router, prefix="/api/v1")
    app.include_router(departments_router, prefix="/api/v1")
    app.include_router(branches_router, prefix="/api/v1")
    app.include_router(job_grades_router, prefix="/api/v1")
    app.include_router(policies_router, prefix="/api/v1")
    app.include_router(shifts_router, prefix="/api/v1")
    app.include_router(job_postings_router, prefix="/api/v1")
    app.include_router(candidates_router, prefix="/api/v1")
    app.include_router(performance_reviews_router, prefix="/api/v1")
    app.include_router(training_courses_router, prefix="/api/v1")
    app.include_router(training_enrollments_router, prefix="/api/v1")
    app.include_router(disciplinary_cases_router, prefix="/api/v1")
    app.include_router(notifications_router, prefix="/api/v1")
    app.include_router(union_memberships_router, prefix="/api/v1")
    app.include_router(company_assets_router, prefix="/api/v1")
    app.include_router(api_keys_router, prefix="/api/v1")
    app.include_router(chart_accounts_router, prefix="/api/v1")
    app.include_router(general_ledger_router, prefix="/api/v1")
    app.include_router(vendors_router, prefix="/api/v1")
    app.include_router(bills_router, prefix="/api/v1")
    app.include_router(customers_router, prefix="/api/v1")
    app.include_router(invoices_router, prefix="/api/v1")
    app.include_router(financial_statements_router, prefix="/api/v1")
    app.include_router(fixed_assets_router, prefix="/api/v1")
    app.include_router(budgets_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(overtime_router, prefix="/api/v1")
    app.include_router(leave_encashment_router, prefix="/api/v1")
    return app


app = create_app()
