import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payslip_disbursement_record import DisbursementStatus, PayslipDisbursementRecord


def record_disbursement_outcome(
    db: Session,
    *,
    org_id: uuid.UUID,
    payslip_id: uuid.UUID,
    status: DisbursementStatus,
    recorded_by: uuid.UUID,
    reference: str | None = None,
    note: str | None = None,
) -> PayslipDisbursementRecord:
    """Records a confirmed outcome for one payslip's disbursement — a new
    row always, never an edit (see the model docstring), so a settled
    retry after an earlier failure keeps the failed attempt visible too."""
    record = PayslipDisbursementRecord(
        org_id=org_id,
        payslip_id=payslip_id,
        status=status,
        reference=reference,
        note=note,
        recorded_by=recorded_by,
    )
    db.add(record)
    db.flush()
    return record


def list_disbursement_outcomes(
    db: Session, *, payslip_id: uuid.UUID
) -> list[PayslipDisbursementRecord]:
    return list(
        db.scalars(
            select(PayslipDisbursementRecord)
            .where(PayslipDisbursementRecord.payslip_id == payslip_id)
            .order_by(PayslipDisbursementRecord.created_at.desc())
        )
    )


def latest_disbursement_status(
    db: Session, *, payslip_id: uuid.UUID
) -> PayslipDisbursementRecord | None:
    return db.scalar(
        select(PayslipDisbursementRecord)
        .where(PayslipDisbursementRecord.payslip_id == payslip_id)
        .order_by(PayslipDisbursementRecord.created_at.desc())
        .limit(1)
    )
