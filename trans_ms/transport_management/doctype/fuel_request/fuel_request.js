// Copyright (c) 2021, Aakvatech Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on('Fuel Request', {
    onload: function (frm) {
        //Load the approve and reject buttons
        var html = '<button style="background-color: green; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.approve_request(\'' + frm + '\');">Approve</button> ';
        html += '<button style="background-color: red; color: #FFF;" class="btn btn-default btn-xs" onclick="cur_frm.cscript.reject_request(\'' + frm + '\');">Reject</button>';
        $(frm.fields_dict.approve_buttons.wrapper).html(html);

    },

    refresh: function (frm, cdt, cdn) {
        frm.events.show_hide_sections(frm);

        // Hide delete buttons for Requested fuel Child Doctype
        $('*[data-fieldname="requested_fuel"]').find('.grid-remove-rows').hide();
        $('*[data-fieldname="requested_fuel"]').find('.grid-remove-all-rows').hide();
        $('*[data-fieldname="requested_fuel"]').find('.grid-add-row').hide();

        // if (cur_frm.doc.status === "Fully Processed") {
        //     frappe.msgprint(locals[cdt][cdn].status);
        //     var row = frm.fields_dict['approved_requests'].grid.grid_rows_by_docname[cdn];

        //     if (row.doc.status == "Approved") {

        //         cur_frm.add_custom_button(__('Purchase Order'), function () {
        //             frm.events.make_purchase_order(frm);
        //         }, __("Make"));
        //         cur_frm.add_custom_button(__('Issue Fuel'), function () {
        //             frm.events.make_stock_entry(frm);
        //         }, __("Make"));
        //     }
        // }
    },

    show_hide_sections: function (frm) {
        frm.toggle_display(['approve_buttons', 'section_requested_fuel'], (frm.doc.requested_fuel.length > 0));
    },

    show_hide_request_fields: function (frm, cdt, cdn) {
        var row = frm.fields_dict['approved_requests'].grid.grid_rows_by_docname[cdn];
        if (row.doc.status == "Approved") {
            row.toggle_editable('disburcement_type', (row.doc.receipt_date == null));
            row.toggle_editable('supplier', (row.doc.receipt_date == null && row.doc.disburcement_type == "From Supplier"));
            row.toggle_editable('receipt_date', ((row.doc.disburcement_type == "From Supplier" && row.doc.supplier) || (row.doc.disburcement_type == "Cash")));
            row.toggle_editable('receipt_time', ((row.doc.disburcement_type == "From Supplier" && row.doc.supplier) || (row.doc.disburcement_type == "Cash")));
        }
    },
    make_stock_entry: function (frm) {
        frappe.model.open_mapped_doc({
            method: "trans_ms.transport_management.doctype.fuel_request.fuel_request.make_stock_entry",
            frm: cur_frm
        });
    },
});



frappe.ui.form.on('Fuel Request Table', {

    form_render(frm, cdt, cdn) {
        frm.fields_dict.requested_fuel.grid.wrapper.find('.grid-delete-row').hide();
        frm.fields_dict.requested_fuel.grid.wrapper.find('.grid-duplicate-row').hide();
        frm.fields_dict.requested_fuel.grid.wrapper.find('.grid-move-row').hide();
        frm.fields_dict.requested_fuel.grid.wrapper.find('.grid-append-row').hide();
        frm.fields_dict.requested_fuel.grid.wrapper.find('.grid-insert-row-below').hide();
        frm.fields_dict.requested_fuel.grid.wrapper.find('.grid-insert-row').hide();
    },


    // create_purchase_order: (frm, cdt, cdn) => {
    //     const row = locals[cdt][cdn];
    //     if (row.purchase_order || row.status != "Approved") return;
    //     console.info("frm", frm);
    //     frappe.call({
    //         method: "trans_ms.transport_management.doctype.fuel_request.fuel_request.create_purchase_order",
    //         args: {
    //             request_doc: frm.doc,
    //             item: row,
    //         },
    //         callback: function (r) {
    //             frm.reload_doc();
    //             frm.refresh_field("requested_fuel");
    //         }
    //     });
    // },
});


// Approve and reject buttons: one call per selected row, then reload once they have all finished.
function decide_fuel_requests(action, label) {
    var selected = cur_frm.get_selected()['requested_fuel'];
    if (!selected) {
        frappe.show_alert(__("Select requests to process first."));
        return;
    }
    frappe.confirm(__("{0} the selected fuel requests?", [label]), function () {
        Promise.all(selected.map(function (name) {
            return frappe.call({
                method: "trans_ms.transport_management.doctype.fuel_request.fuel_request." + action,
                freeze: true,
                args: { request_docname: name },
            });
        })).finally(function () { cur_frm.reload_doc(); });
    });
}

cur_frm.cscript.approve_request = function () { decide_fuel_requests("approve_request", __("Approve")); };
cur_frm.cscript.reject_request = function () { decide_fuel_requests("reject_request", __("Reject")); };
