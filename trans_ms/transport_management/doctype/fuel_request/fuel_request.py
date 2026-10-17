# Copyright (c) 2021, Aakvatech Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import json
import frappe
import time
import datetime
from frappe.model.document import Document
from frappe import _, msgprint
from frappe.model.mapper import get_mapped_doc
from frappe.utils import nowdate
from trans_ms.utlis.dimension import set_dimension
from trans_ms.utlis import guard


class FuelRequest(Document):
    def onload(self):
        trip = frappe.get_doc(self.reference_doctype, self.reference_docname)
        # Load approved fuel for main trip
        if trip.main_route and trip.vehicle:
            consumption = frappe.db.get_value(
                "Vehicle", trip.vehicle, "trans_ms_fuel_consumption"
            )
            route = frappe.db.get_value("Trip Route", trip.main_route, "total_distance")
            approved_fuel = consumption * route
            self.set("main_route", trip.main_route)
            self.set("main_approved_fuel", str(approved_fuel) + " Litres")

        # Load approved fuel for return trip
        if trip.return_route and trip.vehicle:
            consumption = frappe.db.get_value(
                "Vehicle", trip.vehicle, "trans_ms_fuel_consumption"
            )
            route = frappe.db.get_value(
                "Trip Route", trip.return_route, "total_distance"
            )
            approved_fuel = consumption * route
            self.set("return_route", trip.return_route)
            self.set("return_approved_fuel", str(approved_fuel) + " Litres")

    def get_all_children(self, parenttype=None):
        # For getting children
        return []

    def update_children(self):
        """update child tables"""

    def before_save(self):
        for row in self.approved_requests:
            doc = frappe.get_doc("Fuel Request Table", row.name)
            doc.db_set("disburcement_type", row.disburcement_type)
            doc.db_set("supplier", row.supplier)
            doc.db_set("receipt_date", row.receipt_date)
            doc.db_set("receipt_time", row.receipt_time)
            doc.db_set("received_by", row.received_by)

    def load_from_db(self):
        """Load document and children from database and create properties
        from fields"""
        if not getattr(self, "_metaclass", False) and self.meta.issingle:
            single_doc = frappe.db.get_singles_dict(self.doctype)
            if not single_doc:
                single_doc = frappe.new_doc(self.doctype).as_dict()
                single_doc["name"] = self.doctype
                del single_doc["__islocal"]

            super(Document, self).__init__(single_doc)
            self.init_valid_columns()
            self._fix_numeric_types()

        else:
            d = frappe.db.get_value(self.doctype, self.name, "*", as_dict=1)
            if not d:
                frappe.throw(
                    _("{0} {1} not found").format(_(self.doctype), self.name),
                    frappe.DoesNotExistError,
                )

            super(Document, self).__init__(d)

        if self.name == "DocType" and self.doctype == "DocType":
            from frappe.model.meta import doctype_table_fields

            table_fields = doctype_table_fields
        else:
            table_fields = self.meta.get_table_fields()

        for df in table_fields:
            if df.fieldname == "approved_requests":
                # Load approved or rejected requests
                children_main_approved = frappe.db.get_values(
                    df.options,
                    {
                        "parent": self.get("reference_docname"),
                        "parenttype": self.get("reference_doctype"),
                        "parentfield": "main_fuel_request",
                        "status": "Approved",
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                children_main_rejected = frappe.db.get_values(
                    df.options,
                    {
                        "parent": self.get("reference_docname"),
                        "parenttype": self.get("reference_doctype"),
                        "parentfield": "main_fuel_request",
                        "status": "Rejected",
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                children_return_approved = frappe.db.get_values(
                    df.options,
                    {
                        "parent": self.get("reference_docname"),
                        "parenttype": self.get("reference_doctype"),
                        "parentfield": "return_fuel_request",
                        "status": "Approved",
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                children_return_rejected = frappe.db.get_values(
                    df.options,
                    {
                        "parent": self.get("reference_docname"),
                        "parenttype": self.get("reference_doctype"),
                        "parentfield": "return_fuel_request",
                        "status": "Rejected",
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                children = (
                    children_main_approved
                    + children_main_rejected
                    + children_return_approved
                    + children_return_rejected
                )
                if children:
                    self.set(df.fieldname, children)
                else:
                    self.set(df.fieldname, [])
            elif df.fieldname == "requested_fuel":
                # Load requests which are not approved nor rejected
                children_main_requested = frappe.db.get_values(
                    df.options,
                    {
                        "parent": self.get("reference_docname"),
                        "parenttype": self.get("reference_doctype"),
                        "parentfield": "main_fuel_request",
                        "status": "Requested",
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                children_return_requested = frappe.db.get_values(
                    df.options,
                    {
                        "parent": self.get("reference_docname"),
                        "parenttype": self.get("reference_doctype"),
                        "parentfield": "return_fuel_request",
                        "status": "Requested",
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                children = children_main_requested + children_return_requested
                if children:
                    self.set(df.fieldname, children)
                else:
                    self.set(df.fieldname, [])

        # sometimes __setup__ can depend on child values, hence calling again at the end
        if hasattr(self, "__setup__"):
            self.__setup__()

def set_status(doc):
    """Fuel Request status from its trip's fuel rows; `doc` is one Fuel Request Table row."""
    parent_doc_name = frappe.db.get_value("Fuel Request Table", doc, "parent")
    statuses = frappe.get_all(
        "Fuel Request Table", filters={"parent": parent_doc_name}, pluck="status"
    )
    processed = [s for s in statuses if s in ("Approved", "Rejected")]
    parent_request_name = frappe.db.get_value(
        "Fuel Request", {"reference_docname": parent_doc_name}
    )
    if not parent_request_name:
        return
    if not processed:
        status = "Waiting Approval"
    elif len(processed) == len(statuses):
        status = "Fully Processed"
    else:
        status = "Partially Processed"
    frappe.db.set_value("Fuel Request", parent_request_name, "status", status)


@frappe.whitelist()
def approve_request(request_docname, **args):
    return decide(request_docname, "Approved")


@frappe.whitelist()
def reject_request(request_docname, **args):
    return decide(request_docname, "Rejected")


def decide(request_docname, status):
    request, trip = guard.row("Fuel Request Table", request_docname)
    if request.status != "Requested":
        frappe.throw(_("Fuel request {0} is already {1}.").format(request.name, request.status))
    if trip.owner == frappe.session.user:
        frappe.throw(_("You cannot approve or reject fuel for a trip you created."))
    request.db_set(
        {"status": status, "approved_by": guard.me(), "approved_date": nowdate()}
    )
    set_status(request.name)
    return "Request Updated"


# @frappe.whitelist()
# def make_purchase_order(source_name, target_doc=None):

# 	doc = get_mapped_doc("Fuel Request", source_name,	{
# 		"Fuel Request": {
# 			"doctype": "Purchase Order",
# 			"field_map": {

# 			},
# 			"validation": {
# 				"docstatus": ["=", 0],
# 			}
# 		},
# 		"Fuel Request Table": {
# 			"doctype": "Purchase Order Item",
# 			"field_map": {
#                 "name": "fuel_request_table",
# 				"parent":"fuel_request",
#                 "item_code":"item_code",
# 				#"total_cost":"amount",
# 				"quantity": "qty",
# 				#"cost_per_litre": "rate",
# 				source_name:"fuel_request"
# 			},

# 		},
# 	}, target_doc)

# return doc


# @frappe.whitelist()
# def create_purchase_order(request_doc, item):
#     # frappe.throw(request_doc)
#     item = frappe._dict(json.loads(item))
#     request_doc = frappe._dict(json.loads(request_doc))
#     set_warehouse = frappe.get_value(
#         "Vehicle", request_doc.vehicle_plate_number, "trans_ms_fuel_warehouse"
#     )
#     if not set_warehouse:
#         frappe.throw(_("Fuel Stock Warehouse not set in Vehicle"))
#     if item.purchase_order:
#         frappe.throw(_("Purchase Order is already exists"))
#     doc = frappe.new_doc("Purchase Order")
#     doc.company = request_doc.company
#     doc.department = item.supplier
#     doc.supplier = item.supplier
#     doc.schedule_date = nowdate()
#     doc.docstatus = 1
#     doc.set_warehouse = set_warehouse
#     new_item = doc.append("items", {})
#     new_item.item_code = item.item_code
#     new_item.qty = item.quantity
#     new_item.rate = item.cost_per_litre
#     new_item.source_name = "fuel_request"
#     set_dimension(request_doc, doc)
#     set_dimension(request_doc, doc, tr_child=new_item)
#     doc.insert(ignore_permissions=True)
#     frappe.msgprint(_("Purchase Order {0} is created").format(doc.name))
#     frappe.set_value(item.doctype, item.name, "purchase_order", doc.name)
#     return doc.name


@frappe.whitelist()
def make_stock_entry(source_name, target_doc=None):
    guard.doc("Fuel Request", source_name, "read")
    doc = get_mapped_doc(
        "Fuel Request",
        source_name,
        {
            "Fuel Request": {
                "doctype": "Stock Entry",
                "field_map": {},
                "validation": {
                    "docstatus": ["=", 0],
                },
            },
            "Fuel Request Table": {
                "doctype": "Stock Entry Detail",
                "field_map": {
                    "name": "fuel_request_table",
                    "parent": "fuel_request",
                    # "total_cost": "basic_amount",
                    "quantity": "qty",
                    source_name: "fuel_request",
                    # "cost_per_litre": "basic_rate",
                },
            },
        },
        target_doc,
    )
    return doc
