from frappe import _


def get_dashboard_for_pos_closing_entry(data: dict) -> dict:
    """Extend POS Closing Entry dashboard to show linked cash-up variance Journal Entries."""
    data["transactions"].append(
        {
            "label": _("Accounting"),
            "items": ["Journal Entry"],
        }
    )

    # Journal Entry links back via cheque_no (a parent-level Data field),
    # not via a standard Link field — must tell Frappe which field to query.
    data["non_standard_fieldnames"].update(
        {
            "Journal Entry": "cheque_no",
        }
    )

    return data
