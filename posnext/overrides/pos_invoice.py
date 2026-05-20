import frappe
from erpnext.accounts.doctype.pos_invoice.pos_invoice import (
    get_bin_qty,
    get_bundle_availability,
    get_pos_reserved_qty,
)


@frappe.whitelist()
def get_stock_availability(item_code: str, warehouse: str) -> tuple:
    if frappe.db.get_value("Item", item_code, "is_stock_item"):
        is_stock_item = True
        bin_qty = get_bin_qty(item_code, warehouse)
        pos_sales_qty = get_pos_reserved_qty(item_code, warehouse)

        return bin_qty - pos_sales_qty, is_stock_item
    else:
        is_stock_item = True
        if frappe.db.exists("Product Bundle", {"name": item_code, "disabled": 0}):
            return get_bundle_availability(item_code, warehouse), is_stock_item
        else:
            is_stock_item = False
            return 0, is_stock_item
