import frappe
from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry
from frappe import _
from frappe.utils import flt, get_datetime

from posnext.overrides.pos_invoice_merge_log import (
    consolidate_pos_invoices,
    unconsolidate_pos_invoices,
)


@frappe.whitelist()
def get_pos_invoices(start: str, end: str, pos_profile: str, user: str) -> list:
    data = frappe.db.sql(
        """
    select
        name, timestamp(posting_date, posting_time) as "timestamp"
    from
        `tabPOS Invoice`
    where
        owner = %s and docstatus = 1 and pos_profile = %s
    """,
        (user, pos_profile),
        as_dict=1,
    )

    start_dt = get_datetime(start)
    end_dt = get_datetime(end)
    data = [d for d in data if start_dt <= get_datetime(d.timestamp) <= end_dt]

    # need to get taxes and payments so can't avoid get_doc
    data = [frappe.get_doc("POS Invoice", d.name).as_dict() for d in data]
    return data


class PosnextPOSClosingEntry(POSClosingEntry):
    def on_submit(self) -> None:
        consolidate_pos_invoices(closing_entry=self)
        self._maybe_create_cashup_variance_je()

    def on_cancel(self) -> None:
        unconsolidate_pos_invoices(closing_entry=self)
        self._maybe_cancel_cashup_variance_je()

    @frappe.whitelist()
    def retry(self) -> None:
        consolidate_pos_invoices(closing_entry=self)

    def validate_pos_invoices(self) -> None:
        invalid_rows = []
        for d in self.pos_transactions:
            invalid_row = {"idx": d.idx}
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
            if pos_invoice.pos_profile != self.pos_profile:
                invalid_row.setdefault("msg", []).append(
                    _("POS Profile doesn't matches {}").format(
                        frappe.bold(self.pos_profile)
                    )
                )
            if pos_invoice.docstatus != 1:
                invalid_row.setdefault("msg", []).append(
                    _("POS Invoice is not {}").format(frappe.bold("submitted"))
                )
            if pos_invoice.owner != self.user:
                invalid_row.setdefault("msg", []).append(
                    _("POS Invoice isn't created by user {}").format(
                        frappe.bold(self.owner)
                    )
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

    # ------------------------------------------------------------------
    # Cash-up Variance JE
    # ------------------------------------------------------------------

    def _maybe_create_cashup_variance_je(self) -> None:
        enabled, variance_account = frappe.db.get_value(
            "POS Profile",
            self.pos_profile,
            ["custom_create_cashup_variance_je", "custom_cashup_variance_account"],
        )

        if not enabled or not variance_account:
            return

        variance_rows = [
            row for row in self.payment_reconciliation if flt(row.difference) != 0
        ]

        if not variance_rows:
            return

        je = self._build_cashup_variance_je(variance_account, variance_rows)
        je.flags.ignore_permissions = True
        je.insert()
        je.submit()

        frappe.msgprint(
            _("Cash-up Variance Journal Entry {0} created for {1}.").format(
                frappe.bold(je.name),
                frappe.bold(self.name),
            ),
            title=_("Cash-up Variance Posted"),
            indicator="green",
        )

    def _build_cashup_variance_je(
        self, variance_account: str, variance_rows: list
    ) -> "frappe.Document":
        net_variance = sum(flt(row.difference) for row in variance_rows)

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.posting_date = self.posting_date
        je.company = self.company
        je.user_remark = (
            f"POS Closing Entry {self.name} overs and unders/cash-up variance"
        )
        je.cheque_no = self.name
        je.cheque_date = self.posting_date

        # Single net entry for the variance account
        if net_variance > 0:
            je.append(
                "accounts",
                {
                    "account": variance_account,
                    "credit_in_account_currency": flt(net_variance),
                },
            )
        else:
            je.append(
                "accounts",
                {
                    "account": variance_account,
                    "debit_in_account_currency": flt(abs(net_variance)),
                },
            )

        # One row per payment method with a non-zero difference
        for row in variance_rows:
            payment_account = self._get_mop_default_account(row.mode_of_payment)
            if not payment_account:
                frappe.throw(
                    _(
                        "No default account found for Mode of Payment {0} in company {1}. "
                        "Please configure it before closing the POS."
                    ).format(
                        frappe.bold(row.mode_of_payment), frappe.bold(self.company)
                    )
                )

            diff = flt(row.difference)
            if diff > 0:
                je.append(
                    "accounts",
                    {
                        "account": payment_account,
                        "debit_in_account_currency": diff,
                    },
                )
            else:
                je.append(
                    "accounts",
                    {
                        "account": payment_account,
                        "credit_in_account_currency": abs(diff),
                    },
                )

        return je

    def _get_mop_default_account(self, mode_of_payment: str) -> str | None:
        return frappe.db.get_value(
            "Mode of Payment Account",
            {"parent": mode_of_payment, "company": self.company},
            "default_account",
        )

    def _maybe_cancel_cashup_variance_je(self) -> None:
        je_names = frappe.get_all(
            "Journal Entry",
            filters={"cheque_no": self.name, "docstatus": 1, "company": self.company},
            pluck="name",
        )

        for je_name in je_names:
            je = frappe.get_doc("Journal Entry", je_name)
            je.flags.ignore_permissions = True
            je.cancel()
