import logging
import uuid

import httpx

from app.core.db import tenant_session
from app.models.employee import Employee
from app.models.organisation import Organisation
from app.models.payslip import Payslip
from app.models.payslip_delivery import PayslipDelivery, PayslipDeliveryStatus
from app.services.email import send_email_with_attachment
from app.services.payslip_pdf import render_payslip_pdf

logger = logging.getLogger(__name__)


def deliver_payslip_email(
    *, org_id: uuid.UUID, account_id: uuid.UUID, role: str, payslip_id: uuid.UUID
) -> None:
    """Generates the payslip PDF and emails it to the employee, recording
    the attempt (sent or failed) as a new payslip_deliveries row. Safe to
    run as a FastAPI background task: opens its own tenant-scoped session
    rather than reusing the request's, since that session is already
    closed (and committed) by the time a background task runs.
    """
    with tenant_session(org_id, account_id, role) as db:
        payslip = db.get(Payslip, payslip_id)
        if payslip is None:
            return
        employee = db.get(Employee, payslip.employee_id)
        organisation = db.get(Organisation, payslip.org_id)
        if employee is None or organisation is None:
            return

        if not employee.email:
            db.add(
                PayslipDelivery(
                    org_id=org_id,
                    payslip_id=payslip.id,
                    status=PayslipDeliveryStatus.FAILED,
                    recipient_email="",
                    error="employee has no email on file",
                )
            )
            return

        # Rendering is not wrapped: a PDF-generation bug should surface as a
        # real exception, not get silently recorded as a "delivery failure"
        # alongside genuine send failures (missing config, network, API).
        pdf_bytes = render_payslip_pdf(
            organisation=organisation, employee=employee, payslip=payslip
        )

        try:
            message_id = send_email_with_attachment(
                to=employee.email,
                subject=(
                    f"Payslip for {payslip.period_start.isoformat()} "
                    f"to {payslip.period_end.isoformat()}"
                ),
                html_body=(
                    f"<p>Hi {employee.full_name},</p>"
                    f"<p>Your payslip for {payslip.period_start.isoformat()} to "
                    f"{payslip.period_end.isoformat()} is attached.</p>"
                ),
                attachment_bytes=pdf_bytes,
                attachment_filename=f"payslip-{payslip.period_end}.pdf",
            )
        except (RuntimeError, httpx.HTTPError) as exc:
            logger.warning(
                "payslip email delivery failed",
                extra={"payslip_id": str(payslip.id), "error": str(exc)},
            )
            db.add(
                PayslipDelivery(
                    org_id=org_id,
                    payslip_id=payslip.id,
                    status=PayslipDeliveryStatus.FAILED,
                    recipient_email=employee.email,
                    error=str(exc)[:1000],
                )
            )
            return

        db.add(
            PayslipDelivery(
                org_id=org_id,
                payslip_id=payslip.id,
                status=PayslipDeliveryStatus.SENT,
                recipient_email=employee.email,
                provider_message_id=message_id,
            )
        )
