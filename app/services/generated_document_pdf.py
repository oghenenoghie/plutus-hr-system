import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer

from app.models.generated_document import GeneratedDocument


def render_generated_document_pdf(document: GeneratedDocument) -> bytes:
    """Renders a generated document's rendered_content as a simple PDF —
    one paragraph per line, no letterhead styling beyond what the
    template's own text provides. If the document has been signed, a
    signature block is appended (name and timestamp only — not a
    cryptographic signature, see GeneratedDocument's docstring)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("DocBody", parent=styles["Normal"], fontSize=11, leading=16)
    small_style = ParagraphStyle("DocSmall", parent=styles["Normal"], fontSize=9)

    story: list[Flowable] = []
    for line in document.rendered_content.splitlines():
        story.append(Paragraph(line or "&nbsp;", body_style))

    if document.signed_at is not None and document.signed_by_name is not None:
        story.append(Spacer(1, 10 * mm))
        story.append(
            Paragraph(
                f"Signed by {document.signed_by_name} on {document.signed_at.isoformat()}",
                small_style,
            )
        )

    doc.build(story)
    return buffer.getvalue()
