import frappe
from frappe.utils import flt, get_datetime
from frappe import _

@frappe.whitelist()
def get_pos_invoices(start, end, pos_profile, user):
    print("HEEEEEEEEEEEEEEEEERE")
    data = frappe.db.sql(
        """
        SELECT
            name, timestamp(posting_date, posting_time) as "timestamp"
        FROM
            `tabPOS Invoice`
        WHERE
            owner = %s AND docstatus = 1 AND pos_profile = %s
        """,
        (user, pos_profile),
        as_dict=1,
    )

    data = list(filter(lambda d: get_datetime(start) <= get_datetime(d.timestamp) <= get_datetime(end), data))
    # need to get taxes and payments so can't avoid get_doc
    data = [frappe.get_doc("POS Invoice", d.name).as_dict() for d in data]
    return data


from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry
from posnext.overrides.pos_invoice_merge_log import (
    consolidate_pos_invoices,
    unconsolidate_pos_invoices,
)

class PosnextPOSClosingEntry(POSClosingEntry):
    def on_submit(self):
        consolidate_pos_invoices(closing_entry=self)

    def on_cancel(self):
        unconsolidate_pos_invoices(closing_entry=self)

    @frappe.whitelist()
    def retry(self):
        consolidate_pos_invoices(closing_entry=self)

    def validate_pos_invoices(self):
        invalid_rows = []
        for d in self.pos_transactions:
            invalid_row = {"idx": d.idx}
            
            # FIXED: Changed from "Sales Invoice" to "POS Invoice"
            pos_invoice_data = frappe.db.get_values(
                "POS Invoice",
                d.pos_invoice,
                ["pos_profile", "docstatus", "owner"],
                as_dict=1,
            )
            
            if not pos_invoice_data:
                invalid_row.setdefault("msg", []).append(
                    _("POS Invoice {} not found").format(frappe.bold(d.pos_invoice))
                )
                invalid_rows.append(invalid_row)
                continue
                
            pos_invoice = pos_invoice_data[0]
            
            # Original validations
            if pos_invoice.pos_profile != self.pos_profile:
                invalid_row.setdefault("msg", []).append(
                    _("POS Profile doesn't match {}").format(frappe.bold(self.pos_profile))
                )
            if pos_invoice.docstatus != 1:
                invalid_row.setdefault("msg", []).append(
                    _("POS Invoice is not {}").format(frappe.bold("submitted"))
                )
            if pos_invoice.owner != self.user:
                invalid_row.setdefault("msg", []).append(
                    _("POS Invoice isn't created by user {}").format(frappe.bold(self.user))
                )

            if invalid_row.get("msg"):
                invalid_rows.append(invalid_row)

        if not invalid_rows:
            return

        error_list = []
        for row in invalid_rows:
            for msg in row.get("msg"):
                error_list.append(_("Row #{}: {}").format(row.get("idx"), msg))

        frappe.throw(error_list, title=_("Invalid POS Invoices"), as_list=True)