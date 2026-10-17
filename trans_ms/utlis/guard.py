# Copyright (c) 2026, OMER and contributors
# For license information, please see license.txt

"""Permission checks for the whitelisted endpoints. They used to be guest-callable and trusted documents and
user names sent by the browser; now every endpoint loads what it changes from the database and checks the
session user's rights on it."""

import frappe
from frappe.utils import get_fullname


def doc(doctype, name, ptype="write"):
    """The saved document, after checking the session user may `ptype` it."""
    d = frappe.get_doc(doctype, name)
    d.check_permission(ptype)
    return d


def row(child_doctype, name, ptype="write"):
    """A saved child row and its parent document, after checking the session user may `ptype` the parent."""
    child = frappe.get_doc(child_doctype, name)
    return child, doc(child.parenttype, child.parent, ptype)


def name_of(value):
    """A document name from what the desk sends: a name, or the whole document as JSON or a dict."""
    if isinstance(value, str) and value.lstrip().startswith("{"):
        value = frappe.parse_json(value)
    return value.get("name") if isinstance(value, dict) else value


def me():
    return get_fullname(frappe.session.user)
