"""Install hooks + scheduled maintenance cho VN Office AI."""

import frappe

OFFICE_ROLES = ["AI Office User", "AI Office Analyst", "AI Office Manager"]


def after_install():
    ensure_office_roles()
    create_default_settings()
    frappe.db.commit()


def ensure_office_roles():
    """Tạo 3 role của app nếu fixtures chưa nạp. Idempotent."""
    for role in OFFICE_ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({
                "doctype": "Role",
                "role_name": role,
                "desk_access": 1,
                "is_custom": 1,
            }).insert(ignore_permissions=True)


def create_default_settings():
    """Set default cho AI Office Settings nếu chưa cấu hình. Idempotent."""
    s = frappe.get_single("AI Office Settings")
    if not s.default_model:
        s.default_model = "google/gemini-2.5-flash"
        s.fallback_model = "anthropic/claude-haiku-4.5"
        s.analyst_model = "anthropic/claude-sonnet-4.7"
        s.openrouter_base_url = "https://openrouter.ai/api/v1"
        s.mask_pii_before_llm = 1
        s.max_requests_per_user_per_day = 100
        s.request_timeout_seconds = 120
        s.max_tokens_per_request = 8000
        s.audit_log_retention_days = 90
        s.file_storage_backend = "Local"
        s.flags.ignore_permissions = True
        s.save(ignore_permissions=True)


# ───────────────────────── scheduler ─────────────────────────

def cleanup_expired_requests():
    """Daily: xoá Document Request nháp quá hạn retention (chưa submit)."""
    s = frappe.get_single("AI Office Settings")
    days = s.audit_log_retention_days or 90
    cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -days)
    stale = frappe.get_all("AI Office Document Request", filters={
        "docstatus": 0,
        "status": ["in", ["Draft", "Asking Questions", "Failed"]],
        "modified": ["<", cutoff],
    }, pluck="name")
    for name in stale:
        try:
            frappe.delete_doc("AI Office Document Request", name, ignore_permissions=True, force=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "AIO cleanup_expired_requests")
    if stale:
        frappe.db.commit()
