# -*- coding: utf-8 -*-
"""Small shims so one code base installs on Odoo 18, 19 and 20."""
from odoo import models, release

ODOO_MAJOR = int(str(release.version_info[0]).split("~")[-1].split(".")[0])

# Odoo 19+ ignores ``_sql_constraints`` (it only logs a warning), so a model
# declaring constraints that way silently loses them. ``models.Constraint``
# does not exist on Odoo 18. Both forms yield the same PostgreSQL constraint
# name (``<table>_<key>``), so databases upgrade cleanly across versions.
HAS_CONSTRAINT = hasattr(models, "Constraint")


def sql_constraints(namespace, *specs):
    """Declare ``(key, definition, message)`` constraints in a model body."""
    if HAS_CONSTRAINT:
        for key, definition, message in specs:
            namespace["_%s" % key] = models.Constraint(definition, message)
    else:
        namespace["_sql_constraints"] = [tuple(spec) for spec in specs]


def config_param(env, key, default=False):
    """Read a system parameter (``get_param`` was replaced by typed getters in 20)."""
    params = env["ir.config_parameter"].sudo()
    getter = getattr(params, "get_str", None) or params.get_param
    return getter(key) or default


def move_uom_field(env):
    """``stock.move.product_uom`` was renamed ``uom_id`` in Odoo 20."""
    return "product_uom" if "product_uom" in env["stock.move"]._fields else "uom_id"


def uom_decimal_places(uom):
    """Decimal places Tally should use for an Odoo unit of measure."""
    rounding = getattr(uom, "rounding", 0.0) if "rounding" in uom._fields else 0.0
    if not rounding:
        precision = uom.env["decimal.precision"].sudo().search(
            [("name", "in", ("Product Unit", "Product Unit of Measure"))], limit=1)
        return int(precision.digits) if precision else 0
    if rounding >= 1:
        return 0
    text = ("%.6f" % rounding).rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0
