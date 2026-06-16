"""Whitelisted API — Tier 1 template discovery."""

import frappe
from frappe import _


@frappe.whitelist()
def list_for_user(category=None):
    """Liệt kê template active mà user có role phù hợp.

    Lọc theo `required_roles` của template (enforce ở app logic, không phải DocPerm).
    """
    user_roles = set(frappe.get_roles())
    filters = {"is_active": 1}
    if category:
        filters["category"] = category

    out = []
    for t in frappe.get_all(
        "AI Office Template", filters=filters,
        fields=["name", "template_code", "template_name", "category",
                "icon", "description", "source_doctype", "source_required"],
    ):
        required = frappe.get_all(
            "Has Role",
            filters={"parent": t.name, "parenttype": "AI Office Template"},
            pluck="role",
        )
        if not required or (user_roles & set(required)):
            out.append(t)
    return out


@frappe.whitelist()
def get_questions(template):
    """Trả schema câu hỏi của 1 template."""
    frappe.has_permission("AI Office Template", "read", template, throw=True)
    doc = frappe.get_cached_doc("AI Office Template", template)
    return [
        {
            "question_label": q.question_label,
            "field_name": q.field_name,
            "field_type": q.field_type,
            "field_options": q.field_options,
            "is_required": q.is_required,
            "default_value": q.default_value,
            "fetch_from_source": q.fetch_from_source,
            "depends_on": q.depends_on,
            "helper_text": q.helper_text,
        }
        for q in doc.questions
    ]
