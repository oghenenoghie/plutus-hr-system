from fastapi import FastAPI

from app.api.v1.auth import router as auth_router
from app.api.v1.benefits import router as benefits_router
from app.api.v1.contractors import router as contractors_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.employees import router as employees_router
from app.api.v1.expenses import router as expenses_router
from app.api.v1.final_settlement import router as final_settlement_router
from app.api.v1.health import router as health_router
from app.api.v1.leave import router as leave_router
from app.api.v1.loans import router as loans_router
from app.api.v1.pay_runs import router as pay_runs_router
from app.api.v1.simulation import router as simulation_router
from app.api.v1.statutory_liabilities import router as statutory_liabilities_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
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
    return app


app = create_app()
