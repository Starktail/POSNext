frappe.ui.form.on("POS Profile", {
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
