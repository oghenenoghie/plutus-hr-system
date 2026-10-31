"""The approved payroll rule sets for the engine's countries, one module
each, approved by Plutus Technologies from the drafts in docs/countries
(app/compliance/engine/countries/_common.py). Each is a RuleSetTemplate:
built in are the figures its sources settle; each organisation enters the
rest under Tax Settings."""

from app.compliance.engine.countries import ci, gh, gm, ke, rw
from app.compliance.engine.settings import RuleSetTemplate

TEMPLATES: tuple[RuleSetTemplate, ...] = (
    gm.TEMPLATE,
    rw.TEMPLATE,
    rw.TEMPLATE_2027,
    ke.TEMPLATE,
    gh.TEMPLATE,
    ci.TEMPLATE,
)
