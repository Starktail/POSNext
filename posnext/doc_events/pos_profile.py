import frappe
from frappe import _


def validate_pf(doc, method):
    pass


@frappe.whitelist()
def get_pos_profile_branch(pos_profile_name: str) -> dict:
    if not pos_profile_name:
        frappe.throw(_("POS Profile name is required."))

    branch = frappe.db.get_value("POS Profile", pos_profile_name, "branch")
    return {"branch": branch}
