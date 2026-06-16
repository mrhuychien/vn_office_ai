"""Chạy query_definition nội bộ của Analysis Type (Tier 2) — SECURITY-CRITICAL.

query_definition chỉ AOM/SM sửa (trusted), nhưng vẫn defense-in-depth:
- chỉ cho placeholder %(company)s %(from)s %(to)s, bind tham số (không nối chuỗi)
- chặn mọi lệnh ghi/DDL
"""

import re

import frappe

_FORBIDDEN = ("insert", "update", "delete", "drop", "alter", "truncate",
              "grant", "create", "replace", "into", "set ")


def execute_query_definition(analysis_type, *, company, period_from, period_to):
    """Trả về list[dict] dữ liệu nội bộ. Read-only enforced ở app layer."""
    qdef = (analysis_type.query_definition or "").strip()
    if not qdef:
        return []

    lowered = qdef.lower()
    for bad in _FORBIDDEN:
        # so khớp theo từ để tránh false positive (vd cột tên 'created')
        if re.search(rf"\b{re.escape(bad.strip())}\b", lowered):
            frappe.throw(f"Query Definition chứa từ khoá bị cấm: '{bad.strip()}'")

    if not lowered.startswith("select"):
        frappe.throw("Query Definition phải bắt đầu bằng SELECT.")

    params = {
        "company": company,
        "from": period_from,
        "to": period_to,
    }
    # frappe.db.sql với dict params → tự bind an toàn (%(name)s)
    return frappe.db.sql(qdef, params, as_dict=True)
