frappe.ui.form.on("POS Profile", {
  refresh(frm) {
    frm.set_query("custom_cashup_variance_account", function () {
      return {
        filters: {
          root_type: "Expense",
          company: frm.doc.company,
          is_group: 0,
        },
      };
    });
  },
  custom_show_only_list_view: function (frm) {
    if (frm.doc.custom_show_only_list_view) {
      frm.doc.custom_show_only_card_view = 0;
      frm.refresh_field("custom_show_only_card_view");
    }
  },
  custom_show_only_card_view: function (frm) {
    if (frm.doc.custom_show_only_card_view) {
      frm.doc.custom_show_only_list_view = 0;
      frm.refresh_field("custom_show_only_list_view");
    }
  },
});
