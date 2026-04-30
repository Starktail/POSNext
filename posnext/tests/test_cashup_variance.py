import unittest

import frappe
from erpnext.accounts.doctype.pos_profile.test_pos_profile import make_pos_profile
from erpnext.stock.doctype.stock_entry.test_stock_entry import make_stock_entry
from frappe.utils import today

from posnext.overrides.pos_closing_entry import PosnextPOSClosingEntry

COMPANY = "_Test Company"
CASH_MOP = "Cash"
_COUNTER = 0


def _next_fake_name() -> str:
    global _COUNTER
    _COUNTER += 1
    return f"TEST-PCE-{_COUNTER:04d}"


def _get_expense_account() -> str:
    account = frappe.db.get_value(
        "Account",
        {"company": COMPANY, "root_type": "Expense", "is_group": 0},
        "name",
        order_by="name asc",
    )
    if not account:
        frappe.throw(f"No Expense account found in {COMPANY} — cannot run tests.")
    return account


def _get_cash_account() -> str:
    account = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": CASH_MOP, "company": COMPANY},
        "default_account",
    )
    if not account:
        frappe.throw(
            f"No default account for Mode of Payment '{CASH_MOP}' in {COMPANY}."
        )
    return account


def _make_pos_profile_with_variance(variance_account: str) -> "frappe.Document":
    """POS Profile with variance JE enabled, ready for use."""
    pos_profile = make_pos_profile(do_not_insert=True)
    pos_profile.custom_create_cashup_variance_je = 1
    pos_profile.custom_cashup_variance_account = variance_account
    if not frappe.db.exists("POS Profile", pos_profile.name):
        pos_profile.insert()
    else:
        pos_profile.save()
    return pos_profile


def _make_pos_profile_disabled() -> "frappe.Document":
    """POS Profile with variance JE disabled (the default)."""
    pos_profile = make_pos_profile(do_not_insert=True)
    pos_profile.custom_create_cashup_variance_je = 0
    pos_profile.custom_cashup_variance_account = None
    if not frappe.db.exists("POS Profile", pos_profile.name):
        pos_profile.insert()
    else:
        pos_profile.save()
    return pos_profile


def _make_ce(
    pos_profile_name: str,
    variance_rows: list[dict],
    fake_name: str | None = None,
) -> "PosnextPOSClosingEntry":
    """
    Build a PosnextPOSClosingEntry with only the fields the variance JE
    methods need.  The document is NOT saved to the database.
    """
    ce = frappe.new_doc("POS Closing Entry")
    ce.pos_profile = pos_profile_name
    ce.company = COMPANY
    ce.posting_date = today()
    ce.name = fake_name or _next_fake_name()
    for row in variance_rows:
        ce.append("payment_reconciliation", row)
    return ce


class TestCashupVarianceJE(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        make_stock_entry(target="_Test Warehouse - _TC", qty=10, basic_rate=100)
        cls.expense_account = _get_expense_account()
        cls.cash_account = _get_cash_account()

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.sql("delete from `tabPOS Profile`")

    # ------------------------------------------------------------------
    # 8.2 — feature disabled
    # ------------------------------------------------------------------

    def test_no_je_when_disabled(self):
        pos_profile = _make_pos_profile_disabled()
        ce = _make_ce(
            pos_profile.name,
            [
                {
                    "mode_of_payment": CASH_MOP,
                    "expected_amount": 1000,
                    "closing_amount": 900,
                    "difference": -100,
                }
            ],
        )
        ce._maybe_create_cashup_variance_je()

        count = frappe.db.count(
            "Journal Entry", {"cheque_no": ce.name, "docstatus": ["!=", 2]}
        )
        self.assertEqual(count, 0)

    # ------------------------------------------------------------------
    # 8.3 — all differences zero
    # ------------------------------------------------------------------

    def test_no_je_when_all_balanced(self):
        pos_profile = _make_pos_profile_with_variance(self.expense_account)
        ce = _make_ce(
            pos_profile.name,
            [
                {
                    "mode_of_payment": CASH_MOP,
                    "expected_amount": 1000,
                    "closing_amount": 1000,
                    "difference": 0,
                }
            ],
        )
        ce._maybe_create_cashup_variance_je()

        count = frappe.db.count(
            "Journal Entry", {"cheque_no": ce.name, "docstatus": ["!=", 2]}
        )
        self.assertEqual(count, 0)

    # ------------------------------------------------------------------
    # 8.4 — under (cashier short)
    # ------------------------------------------------------------------

    def test_je_created_for_under(self):
        pos_profile = _make_pos_profile_with_variance(self.expense_account)
        ce = _make_ce(
            pos_profile.name,
            [
                {
                    "mode_of_payment": CASH_MOP,
                    "expected_amount": 1000,
                    "closing_amount": 900,
                    "difference": -100,
                }
            ],
        )
        ce._maybe_create_cashup_variance_je()

        je_name = frappe.db.get_value(
            "Journal Entry", {"cheque_no": ce.name, "docstatus": 1}, "name"
        )
        self.assertIsNotNone(je_name, "JE should be created for an under")

        je = frappe.get_doc("Journal Entry", je_name)
        total_debit = sum(r.debit_in_account_currency for r in je.accounts)
        total_credit = sum(r.credit_in_account_currency for r in je.accounts)
        self.assertAlmostEqual(
            total_debit, total_credit, places=2, msg="JE must balance"
        )
        self.assertAlmostEqual(total_debit, 100, places=2)

        # Variance account debited (recording the loss)
        var_rows = [r for r in je.accounts if r.account == self.expense_account]
        self.assertTrue(var_rows, "Variance account row missing from JE")
        self.assertAlmostEqual(var_rows[0].debit_in_account_currency, 100, places=2)

    # ------------------------------------------------------------------
    # 8.5 — over (cashier surplus)
    # ------------------------------------------------------------------

    def test_je_created_for_over(self):
        pos_profile = _make_pos_profile_with_variance(self.expense_account)
        ce = _make_ce(
            pos_profile.name,
            [
                {
                    "mode_of_payment": CASH_MOP,
                    "expected_amount": 1000,
                    "closing_amount": 1050,
                    "difference": 50,
                }
            ],
        )
        ce._maybe_create_cashup_variance_je()

        je_name = frappe.db.get_value(
            "Journal Entry", {"cheque_no": ce.name, "docstatus": 1}, "name"
        )
        self.assertIsNotNone(je_name, "JE should be created for an over")

        je = frappe.get_doc("Journal Entry", je_name)
        total_debit = sum(r.debit_in_account_currency for r in je.accounts)
        total_credit = sum(r.credit_in_account_currency for r in je.accounts)
        self.assertAlmostEqual(
            total_debit, total_credit, places=2, msg="JE must balance"
        )
        self.assertAlmostEqual(total_credit, 50, places=2)

        # Variance account credited (recording the gain)
        var_rows = [r for r in je.accounts if r.account == self.expense_account]
        self.assertTrue(var_rows, "Variance account row missing from JE")
        self.assertAlmostEqual(var_rows[0].credit_in_account_currency, 50, places=2)

    # ------------------------------------------------------------------
    # 8.6 — JE balances for mixed over/under
    # ------------------------------------------------------------------

    def test_je_balanced_for_mixed(self):
        """Net under of 50 (cash -100, cash +50) → JE must balance."""
        pos_profile = _make_pos_profile_with_variance(self.expense_account)
        ce = _make_ce(
            pos_profile.name,
            [
                {
                    "mode_of_payment": CASH_MOP,
                    "expected_amount": 1000,
                    "closing_amount": 900,
                    "difference": -100,
                },
                {
                    "mode_of_payment": CASH_MOP,
                    "expected_amount": 500,
                    "closing_amount": 550,
                    "difference": 50,
                },
            ],
        )
        variance_rows = [
            row
            for row in ce.payment_reconciliation
            if frappe.utils.flt(row.difference) != 0
        ]
        je = ce._build_cashup_variance_je(self.expense_account, variance_rows)

        total_debit = sum(r.debit_in_account_currency or 0 for r in je.accounts)
        total_credit = sum(r.credit_in_account_currency or 0 for r in je.accounts)
        self.assertAlmostEqual(
            total_debit, total_credit, places=2, msg="Mixed JE must balance"
        )

    # ------------------------------------------------------------------
    # 8.7 — cancel cancels the JE
    # ------------------------------------------------------------------

    def test_cancel_cancels_je(self):
        pos_profile = _make_pos_profile_with_variance(self.expense_account)
        ce = _make_ce(
            pos_profile.name,
            [
                {
                    "mode_of_payment": CASH_MOP,
                    "expected_amount": 1000,
                    "closing_amount": 900,
                    "difference": -100,
                }
            ],
        )
        ce._maybe_create_cashup_variance_je()

        je_name = frappe.db.get_value(
            "Journal Entry", {"cheque_no": ce.name, "docstatus": 1}, "name"
        )
        self.assertIsNotNone(je_name, "JE must exist before cancel")

        ce._maybe_cancel_cashup_variance_je()

        docstatus = frappe.db.get_value("Journal Entry", je_name, "docstatus")
        self.assertEqual(docstatus, 2, "JE should be cancelled")

    # ------------------------------------------------------------------
    # 8.8 — missing MOP account raises
    # ------------------------------------------------------------------

    def test_throws_on_missing_mop_account(self):
        pos_profile = _make_pos_profile_with_variance(self.expense_account)
        ce = _make_ce(pos_profile.name, [])

        # "Cheque" MOP has no default_account configured for _Test Company
        variance_rows = [frappe._dict({"mode_of_payment": "Cheque", "difference": -50})]
        with self.assertRaises(frappe.ValidationError):
            ce._build_cashup_variance_je(self.expense_account, variance_rows)
