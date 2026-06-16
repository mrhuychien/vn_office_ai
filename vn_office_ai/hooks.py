app_name = "vn_office_ai"
app_title = "VN Office AI"
app_publisher = "Nguyen Huy Chien"
app_description = "AI văn phòng cho doanh nghiệp Việt — soạn tài liệu & phân tích kế toán native trên ERPNext v16"
app_email = "mrhuychien@gmail.com"
app_license = "mit"

# ERPNext + bản địa hoá VN. erpnextvn cung cấp CoA TT200/TT133 + thuế VN.
# Nếu erpnextvn chưa publish lên app source, cài thủ công: bench get-app erpnextvn <git-url>
required_apps = ["frappe/erpnext"]

# ═══════════════════════════ Assets ═══════════════════════════
app_include_css = "/assets/vn_office_ai/css/vn_office_ai.css"

# ═══════════════════════════ Fixtures ═══════════════════════════
# LƯU Ý: KHÔNG export custom_docperm.json (từng gây KeyError khi migrate).
# Permission để trong DocType JSON `permissions` array + install.py.
fixtures = [
    {
        "dt": "Role",
        "filters": [["name", "in", [
            "AI Office User", "AI Office Analyst", "AI Office Manager",
        ]]],
    },
    {
        "dt": "Custom Field",
        "filters": [["name", "in", [
            "Employee-custom_cccd",
        ]]],
    },
    {"dt": "AI Office Template", "filters": [["template_code", "like", "TPL-%"]]},
    {"dt": "AI Office Analysis Type", "filters": [["type_code", "like", "ANL-%"]]},
    {"dt": "Print Format", "filters": [["name", "like", "AIO %"]]},
    {"dt": "Notification", "filters": [["name", "like", "AIO %"]]},
    {"dt": "Workspace", "filters": [["name", "=", "VN Office AI"]]},
]

# ═══════════════════════════ Doc Events ═══════════════════════════
doc_events = {
    "AI Office Document Request": {
        "validate": "vn_office_ai.vn_office_ai.doctype.ai_office_document_request.ai_office_document_request.validate_request",
        "before_submit": "vn_office_ai.vn_office_ai.doctype.ai_office_document_request.ai_office_document_request.before_submit_request",
        "on_submit": "vn_office_ai.vn_office_ai.doctype.ai_office_document_request.ai_office_document_request.on_submit_request",
        "on_cancel": "vn_office_ai.vn_office_ai.doctype.ai_office_document_request.ai_office_document_request.on_cancel_request",
    },
    # Phase 3:
    "AI Office Analysis Job": {
        "validate": "vn_office_ai.vn_office_ai.doctype.ai_office_analysis_job.ai_office_analysis_job.validate_job",
        "before_submit": "vn_office_ai.vn_office_ai.doctype.ai_office_analysis_job.ai_office_analysis_job.before_submit_job",
        "on_submit": "vn_office_ai.vn_office_ai.doctype.ai_office_analysis_job.ai_office_analysis_job.on_submit_job",
        "on_cancel": "vn_office_ai.vn_office_ai.doctype.ai_office_analysis_job.ai_office_analysis_job.on_cancel_job",
    },
}

# ═══════════════════════════ Permission query (If Owner ở list view) ═══════════════════════════
permission_query_conditions = {
    "AI Office Document Request": "vn_office_ai.api.document.get_permission_query_conditions",
    "AI Office Analysis Job": "vn_office_ai.api.analysis.get_permission_query_conditions",
}
has_permission = {
    "AI Office Document Request": "vn_office_ai.api.document.has_app_permission",
    "AI Office Analysis Job": "vn_office_ai.api.analysis.has_app_permission",
}

# ═══════════════════════════ Jinja helpers (Print Format Tier 1) ═══════════════════════════
jinja = {
    "methods": [
        "vn_office_ai.utils.jinja_helpers.so_tien_bang_chu",
        "vn_office_ai.utils.jinja_helpers.format_vnd",
    ],
}

# ═══════════════════════════ Install ═══════════════════════════
after_install = "vn_office_ai.install.after_install"

# ═══════════════════════════ Scheduler ═══════════════════════════
scheduler_events = {
    "daily": [
        "vn_office_ai.install.cleanup_expired_requests",
    ],
}
