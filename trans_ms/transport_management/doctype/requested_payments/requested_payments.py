# Copyright (c) 2022, Aakvatech Limited and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
import time
import datetime
import json
from frappe.model.document import Document
from frappe.utils import flt, comma_or, nowdate
from frappe import msgprint, _
from trans_ms.utlis import guard


class RequestedPayments(Document):
    def onload(self):
        pass

    def get_all_children(self, parenttype=None):
        # For getting children
        return self.get("payments_reference") or []

    def update_children(self):
        """update child tables"""
        self.update_child_table("payments_reference")

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
            # Load details for payments already paid
            if df.fieldname == "payments_reference":
                children = frappe.db.get_values(
                    df.options,
                    {
                        "parent": self.name,
                        "parenttype": self.doctype,
                        "parentfield": df.fieldname,
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                if children:
                    self.set(df.fieldname, children)
                else:
                    self.set(df.fieldname, [])
            elif (
                df.fieldname == "requested_funds"
            ):  # Load requests which are not approved nor rejected
                children = frappe.db.get_values(
                    df.options,
                    {
                        "parent": ["=", self.get("reference_docname")],
                        "parenttype": ["=", self.get("reference_doctype")],
                        "parentfield": [
                            "in",
                            (
                                "requested_funds",
                                "main_requested_funds",
                                "return_requested_funds",
                            ),
                        ],
                        "request_status": [
                            "in",
                            ("open", "Requested", "Recommended", "Pre-Approved"),
                        ],
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                if children:
                    self.set(df.fieldname, children)
                else:
                    self.set(df.fieldname, [])
            elif df.fieldname == "accounts_approval":
                children = frappe.db.get_values(
                    "Requested Funds Details",
                    {
                        "parent": ["=", self.get("reference_docname")],
                        "parenttype": ["=", self.get("reference_doctype")],
                        "parentfield": [
                            "in",
                            (
                                "requested_funds",
                                "main_requested_funds",
                                "return_requested_funds",
                            ),
                        ],
                        "request_status": [
                            "in",
                            (
                                "Approved",
                                "Rejected",
                                "Accounts Approved",
                                "Accounts Rejected",
                                "Accounts Cancelled",
                            ),
                        ],
                    },
                    "*",
                    as_dict=True,
                    order_by="idx asc",
                )
                if children:
                    for child in children:
                        child.reference = child.name
                    self.set(df.fieldname, children)
                else:
                    self.set(df.fieldname, [])

        # sometimes __setup__ can depend on child values, hence calling again at the end
        if hasattr(self, "__setup__"):
            self.__setup__()


def validate_requested_funds(doc):
    open_requests = [r for r in doc.requested_funds if r.request_status == "open"]
    if open_requests:
        request_status = make_funds_request(
            reference_doctype=doc.doctype,
            reference_docname=doc.name,
            company=doc.company,
        )
        if request_status in ("Request Inserted", "Request Updated"):
            for open_request in open_requests:
                open_request.set("request_status", "Requested")


@frappe.whitelist()
def request_funds(**args):
    guard.doc(args.get("reference_doctype"), args.get("reference_docname"))
    return make_funds_request(**args)


def make_funds_request(**args):
    args = frappe._dict(args)
    existing_payment_request = frappe.db.get_value(
        "Requested Payments",
        {
            "reference_doctype": args.reference_doctype,
            "reference_docname": args.reference_docname,
        },
    )
    if existing_payment_request:
        doc = frappe.get_doc("Requested Payments", existing_payment_request)
        doc.db_set("approval_status", "Waiting Approval")
        if args.company:
            doc.db_set("company", args.company)
        return "Request Updated"

    request = frappe.new_doc("Requested Payments")
    request.update(
        {
            "reference_doctype": args.reference_doctype,
            "reference_docname": args.reference_docname,
            "company": args.company
            or frappe.db.get_value(args.reference_doctype, args.reference_docname, "company"),
            "customer": args.customer,
            "vehicle_no": args.vehicle_no,
            "driver": args.driver,
            "trip_route": args.trip_route,
            "approval_status": "Waiting Approval",
            "payment_status": "Waiting Approval",
        }
    )
    request.insert(ignore_permissions=True)
    return "Request Inserted"


# A fund row moves Requested -> (Recommended | Recommended Against) -> Approved | Rejected. Whoever decides
# needs write access to the trip, and nobody decides on money they asked for themselves.
DECISIONS = {
    "Recommended": ("0", "recommended_by", "recommended_on"),
    "Recommended Against": ("0", "recommended_by", "recommended_on"),
    "Approved": ("1", "approved_by", "approved_on"),
    "Rejected": ("2", "approved_by", "approved_on"),
}


def decide(request_docname, status, comment=None):
    request, parent = guard.row("Requested Funds Details", request_docname)
    if request.request_status in ("Approved", "Rejected", "Accounts Approved"):
        frappe.throw(
            _("Fund request {0} is already {1}.").format(request.name, request.request_status)
        )
    if (request.requested_by or parent.owner) == frappe.session.user:
        frappe.throw(_("You cannot decide on a fund request you made."))
    hidden, by_field, on_field = DECISIONS[status]
    values = {
        "request_status": status,
        "request_hidden_status": hidden,
        by_field: guard.me(),
        on_field: frappe.utils.now(),
    }
    if status in ("Approved", "Rejected"):
        values["approved_date"] = nowdate()
    request.db_set(values)
    return "Request Updated"


@frappe.whitelist()
def recommend_request(request_docname, **args):
    return decide(request_docname, "Recommended")


@frappe.whitelist()
def recommend_against_request(request_docname, **args):
    return decide(request_docname, "Recommended Against")


@frappe.whitelist()
def approve_request(request_docname, **args):
    return decide(request_docname, "Approved")


@frappe.whitelist()
def reject_request(request_docname, **args):
    return decide(request_docname, "Rejected")


def ledger_disabled():
    frappe.throw(
        _(
            "Accounts approval here wrote ledger entries without a voucher and deleted them on cancel, so it "
            "is switched off. Disburse an approved fund from its trip instead: that drafts a Journal Entry "
            "for accounts to check and submit."
        )
    )


@frappe.whitelist()
def accounts_approval(**args):
    ledger_disabled()


@frappe.whitelist()
def accounts_cancel(**args):
    ledger_disabled()


@frappe.whitelist()
def reference_payment(**args):
    args = frappe._dict(args)
    parent = guard.doc("Requested Payments", args.parent)
    request = frappe.new_doc("Reference Payment Table")
    request.update(
        {
            "parent": parent.name,
            "parentfield": "payments_reference",
            "parenttype": "Requested Payments",
            "date_of_payment": args.date_of_payment,
            "accounting_system": args.accounting_system,
            "amount": args.amount,
            "currency": args.currency,
            "reference_no": args.reference_no,
            "status": "paid",
        }
    )
    request.insert(ignore_permissions=True)
    parent.db_set("payment_status", args.payment_status)
    return "inserted"


@frappe.whitelist()
def make_payment(source_name, target_doc=None, ignore_permissions=False):
    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Pay"
    pe.posting_date = nowdate()
    pe.mode_of_payment = "Cash"
    pe.party_type = "Employee"
    pe.allocate_payment_amount = 1
    return pe
