import re

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(body_template: str, context: dict[str, str]) -> str:
    """Fills {{placeholder}} tokens from context; a token with no matching
    key is left blank rather than raising — a template author gets a
    visibly empty spot to notice and fix, not a failed generation."""
    return _PLACEHOLDER.sub(lambda match: context.get(match.group(1), ""), body_template)
