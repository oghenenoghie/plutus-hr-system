from app.domain.document_templates import render_template


def test_fills_known_placeholders() -> None:
    result = render_template(
        "Dear {{full_name}}, welcome to {{org_name}}.", {"full_name": "Ada", "org_name": "Acme"}
    )
    assert result == "Dear Ada, welcome to Acme."


def test_unknown_placeholder_renders_blank() -> None:
    result = render_template("Hello {{missing}}!", {})
    assert result == "Hello !"


def test_no_placeholders_is_a_no_op() -> None:
    assert render_template("Plain text.", {"x": "y"}) == "Plain text."
