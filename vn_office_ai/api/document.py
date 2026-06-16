"""Whitelisted API — Tier 1 document generation.

Luồng: prepare → (prefill_from_source) → điền field → generate (AI foreground) → Submit.
"""

import frappe
from frappe import _


# ───────────────────────── prepare / prefill ─────────────────────────

@frappe.whitelist()
def prepare(template, source_docname=None):
    """Tạo Document Request nháp; prefill field từ source nếu có.

    Returns: tên Document Request mới.
    """
    tpl = frappe.get_cached_doc("AI Office Template", template)

    req = frappe.new_doc("AI Office Document Request")
    req.template = template
    req.status = "Asking Questions"

    # khởi tạo field_values theo schema câu hỏi
    for q in tpl.questions:
        req.append("field_values", {
            "field_name": q.field_name,
            "field_label": q.question_label,
            "field_type": q.field_type,
            "value_text": q.default_value or "",
            "source_of_value": "Default" if q.default_value else "User Input",
        })

    if source_docname and tpl.source_doctype:
        frappe.has_permission(tpl.source_doctype, "read", source_docname, throw=True)
        req.source_docname = source_docname
        _prefill(req, tpl, source_docname)

    req.insert()
    return req.name


@frappe.whitelist()
def prefill_from_source(request_name, source_docname):
    """Điền lại field_values từ source record (khi user đổi source trên form)."""
    req = frappe.get_doc("AI Office Document Request", request_name)
    _check_owner_or_manager(req)
    tpl = frappe.get_cached_doc("AI Office Template", req.template)
    if not tpl.source_doctype:
        return
    frappe.has_permission(tpl.source_doctype, "read", source_docname, throw=True)
    req.source_docname = source_docname
    _prefill(req, tpl, source_docname)
    req.save()
    return req.name


def _prefill(req, tpl, source_docname):
    """Set value_text cho các field có fetch_from_source."""
    src = frappe.get_doc(tpl.source_doctype, source_docname)
    by_name = {fv.field_name: fv for fv in req.field_values}
    for q in tpl.questions:
        if not q.fetch_from_source:
            continue
        value = _resolve_dotted(src, q.fetch_from_source)
        if value is None:
            continue
        fv = by_name.get(q.field_name)
        if fv:
            fv.value_text = str(value)
            fv.source_of_value = "Fetched From Source"


def _resolve_dotted(doc, path):
    """Hỗ trợ path 'field' hoặc 'link_field.target_field' (1 cấp)."""
    if "." not in path:
        return doc.get(path)
    link_field, target = path.split(".", 1)
    link_val = doc.get(link_field)
    if not link_val:
        return None
    meta_field = doc.meta.get_field(link_field)
    if not meta_field or meta_field.fieldtype not in ("Link", "Dynamic Link"):
        return None
    target_dt = meta_field.options
    try:
        return frappe.db.get_value(target_dt, link_val, target)
    except Exception:
        return None


# ───────────────────────── generate (AI foreground) ─────────────────────────

@frappe.whitelist()
def generate(request_name, regenerate=0):
    """Gọi AI soạn tài liệu (đồng bộ). Set preview_html + generated_file.

    Permission: owner của request hoặc Manager.
    """
    req = frappe.get_doc("AI Office Document Request", request_name)
    _check_owner_or_manager(req)

    if req.docstatus != 0:
        frappe.throw(_("Chỉ tạo được khi tài liệu đang ở trạng thái nháp."))

    missing = req.get_missing_required_fields()
    if missing:
        frappe.throw(_("Còn thiếu thông tin bắt buộc: {0}").format(", ".join(missing)))

    _enforce_daily_quota()

    req.db_set("status", "Generating")
    frappe.db.commit()  # để UI thấy trạng thái Generating nếu reload

    try:
        from vn_office_ai.llm import client, prompt
        from vn_office_ai.utils import output_builder

        messages = prompt.build_document_prompt(req)
        res = client.chat_completion(messages, purpose="document")

        html_body = _strip_code_fences(res["text"])
        file_url = output_builder.render_output(req, html_body)

        s = frappe.get_cached_doc("AI Office Settings")
        update = {
            "preview_html": html_body,
            "generated_file": file_url,
            "status": "Generated",
            "error_message": "",
            "llm_model_used": res["model"],
            "llm_input_tokens": res["input_tokens"],
            "llm_output_tokens": res["output_tokens"],
            "llm_cost_usd": res["cost_usd"],
            "llm_duration_ms": res["duration_ms"],
        }
        if s.log_full_prompt:
            update["prompt_sent"] = frappe.as_json(messages)
        if s.log_full_response and res.get("raw"):
            update["response_received"] = frappe.as_json(res["raw"])

        req.db_set(update)
        frappe.db.commit()
    except Exception as e:
        req.db_set("status", "Failed")
        req.db_set("error_message", str(e))
        frappe.db.commit()
        frappe.log_error(frappe.get_traceback(), "AIO document.generate")
        frappe.throw(_("Tạo tài liệu thất bại: {0}").format(str(e)))

    return {
        "status": req.status,
        "preview_html": req.preview_html,
        "file": req.generated_file,
    }


# ───────────────────────── permission hooks ─────────────────────────

def get_permission_query_conditions(user):
    """If Owner ở list view: user thường chỉ thấy request của mình."""
    if not user:
        user = frappe.session.user
    if _is_manager(user):
        return ""
    return f"`tabAI Office Document Request`.`requested_by` = {frappe.db.escape(user)}"


def has_app_permission(doc, user=None, permission_type=None):
    """Document-level: owner hoặc manager."""
    user = user or frappe.session.user
    if _is_manager(user):
        return True
    return doc.requested_by == user


# ───────────────────────── helpers ─────────────────────────

MANAGER_ROLES = {"System Manager", "AI Office Manager"}


def _is_manager(user):
    return bool(MANAGER_ROLES & set(frappe.get_roles(user)))


def _check_owner_or_manager(req):
    user = frappe.session.user
    if _is_manager(user):
        return
    if req.requested_by != user:
        frappe.throw(_("Bạn chỉ thao tác được trên tài liệu của mình."), frappe.PermissionError)


def _enforce_daily_quota():
    s = frappe.get_cached_doc("AI Office Settings")
    limit = s.max_requests_per_user_per_day or 0
    if limit <= 0:
        return
    today = frappe.utils.today()
    count = frappe.db.count("AI Office Document Request", {
        "requested_by": frappe.session.user,
        "request_date": today,
    })
    if count >= limit:
        frappe.throw(_("Bạn đã đạt giới hạn {0} tài liệu/ngày.").format(limit))


def _strip_code_fences(text):
    raw = (text or "").strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.lower().startswith("html"):
                raw = raw[4:]
            raw = raw.strip()
    return raw
