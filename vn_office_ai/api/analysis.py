"""Whitelisted API — Tier 2 AI Analyst.

Luồng: run (background) → reviewer duyệt từng finding → commit (tạo JE/SR draft) → Submit job.
Mọi action nhạy cảm (approve, commit) hard-check role, KHÔNG tin DocPerm UI.
"""

import frappe
from frappe import _


# ───────────────────────── run ─────────────────────────

@frappe.whitelist()
def run(job_name):
    """Kick off background analysis. (Draft → Analyzing)"""
    job = frappe.get_doc("AI Office Analysis Job", job_name)
    _check_owner_or_manager(job)
    _check_analyst_role(job)
    _validate_inputs(job)
    _enforce_daily_quota()

    job.db_set("status", "Analyzing")
    frappe.enqueue(
        "vn_office_ai.jobs.analysis.run_analysis",
        queue="long", timeout=1500, job_name=job_name,
        enqueue_after_commit=True,
    )
    return {"status": "Analyzing",
            "message": _("Đang phân tích nền. Bạn sẽ nhận thông báo khi xong.")}


# ───────────────────────── review ─────────────────────────

@frappe.whitelist()
def approve_finding(job_name, finding_no, decision, final_payload=None, note=None):
    """Duyệt 1 finding. decision: Approved|Rejected|Modified|Skipped.

    HARD CHECK: role ∈ reviewer_roles + permlevel 1 write.
    """
    if decision not in ("Approved", "Rejected", "Modified", "Skipped"):
        frappe.throw(_("Quyết định không hợp lệ."))

    job = frappe.get_doc("AI Office Analysis Job", job_name)
    _check_reviewer_role(job)
    if not job.has_permission("write"):
        frappe.throw(_("Không có quyền duyệt."), frappe.PermissionError)

    finding = next((f for f in job.findings if f.finding_no == finding_no), None)
    if not finding:
        frappe.throw(_("Không tìm thấy đề xuất {0}").format(finding_no))

    finding.review_status = decision
    finding.reviewed_by = frappe.session.user
    finding.reviewed_at = frappe.utils.now_datetime()
    finding.review_note = note
    if decision == "Modified":
        if not final_payload:
            frappe.throw(_("Đề xuất sửa (Modified) cần payload cuối."))
        finding.final_payload = final_payload

    job.save()
    return {"status": job.status, "pending": job.pending_findings}


@frappe.whitelist()
def bulk_review(job_name, decision, severity=None):
    """Duyệt hàng loạt finding đang Pending (lọc theo severity nếu có)."""
    if decision not in ("Approved", "Rejected", "Skipped"):
        frappe.throw(_("Bulk chỉ hỗ trợ Approved/Rejected/Skipped."))

    job = frappe.get_doc("AI Office Analysis Job", job_name)
    _check_reviewer_role(job)
    if not job.has_permission("write"):
        frappe.throw(_("Không có quyền duyệt."), frappe.PermissionError)

    now = frappe.utils.now_datetime()
    n = 0
    for f in job.findings:
        if f.review_status == "Pending" and (not severity or f.severity == severity):
            f.review_status = decision
            f.reviewed_by = frappe.session.user
            f.reviewed_at = now
            n += 1
    job.save()
    return {"status": job.status, "pending": job.pending_findings, "reviewed": n}


# ───────────────────────── commit ─────────────────────────

@frappe.whitelist()
def commit(job_name):
    """Tạo chứng từ nháp từ findings approved. (Ready To Commit → Committed)"""
    job = frappe.get_doc("AI Office Analysis Job", job_name)
    _check_reviewer_role(job)
    if not job.has_permission("submit"):
        frappe.throw(_("Không có quyền commit."), frappe.PermissionError)
    if job.pending_findings != 0:
        frappe.throw(_("Còn {0} đề xuất chưa duyệt.").format(job.pending_findings))
    if (job.approved_findings + job.modified_findings) == 0:
        frappe.throw(_("Không có đề xuất nào được duyệt để tạo chứng từ."))

    from vn_office_ai.utils import output_builder
    result = output_builder.commit_job(job)
    return result


@frappe.whitelist()
def retry_commit(job_name):
    """Thử lại các finding commit lỗi (committed=0 + commit_error)."""
    job = frappe.get_doc("AI Office Analysis Job", job_name)
    _check_reviewer_role(job)
    if not job.has_permission("submit"):
        frappe.throw(_("Không có quyền commit."), frappe.PermissionError)
    from vn_office_ai.utils import output_builder
    return output_builder.commit_job(job, retry_only=True)


# ───────────────────────── permission hooks ─────────────────────────

def get_permission_query_conditions(user):
    if not user:
        user = frappe.session.user
    if _is_manager(user) or _is_reviewer_any(user):
        return ""
    return f"`tabAI Office Analysis Job`.`requested_by` = {frappe.db.escape(user)}"


def has_app_permission(doc, user=None, permission_type=None):
    user = user or frappe.session.user
    if _is_manager(user) or _is_reviewer_any(user):
        return True
    return doc.requested_by == user


# ───────────────────────── helpers ─────────────────────────

MANAGER_ROLES = {"System Manager", "AI Office Manager"}
REVIEWER_ANY = {"Accounts Manager", "Stock Manager"}


def _is_manager(user):
    return bool(MANAGER_ROLES & set(frappe.get_roles(user)))


def _is_reviewer_any(user):
    return bool(REVIEWER_ANY & set(frappe.get_roles(user)))


def _check_owner_or_manager(job):
    user = frappe.session.user
    if _is_manager(user):
        return
    if job.requested_by != user:
        frappe.throw(_("Bạn chỉ thao tác được trên job của mình."), frappe.PermissionError)


def _check_analyst_role(job):
    """User phải có role trong analysis_type.analyst_roles (hoặc là manager)."""
    user = frappe.session.user
    if _is_manager(user):
        return
    allowed = frappe.get_all(
        "Has Role",
        filters={"parent": job.analysis_type, "parenttype": "AI Office Analysis Type"},
        pluck="role",
    )
    # analyst_roles + reviewer_roles đều có thể chạy
    if not (set(frappe.get_roles(user)) & set(allowed)):
        frappe.throw(_("Bạn không có quyền chạy loại phân tích này."), frappe.PermissionError)


def _check_reviewer_role(job):
    """User phải có role trong analysis_type.reviewer_roles (hoặc là manager)."""
    user = frappe.session.user
    if _is_manager(user):
        return
    atype = frappe.get_cached_doc("AI Office Analysis Type", job.analysis_type)
    reviewer_roles = {r.role for r in atype.reviewer_roles}
    if not (set(frappe.get_roles(user)) & reviewer_roles):
        frappe.throw(_("Bạn không có quyền duyệt loại phân tích này."), frappe.PermissionError)


def _validate_inputs(job):
    atype = frappe.get_cached_doc("AI Office Analysis Type", job.analysis_type)
    if job.period_from > job.period_to:
        frappe.throw(_("Từ ngày phải ≤ Đến ngày."))
    if atype.input_mode in ("File Upload Only", "Both"):
        has_file = any(s.source_type == "File Upload" and s.file for s in job.input_files)
        if atype.input_mode == "File Upload Only" and not has_file:
            frappe.throw(_("Loại phân tích này yêu cầu upload file."))


def _enforce_daily_quota():
    s = frappe.get_cached_doc("AI Office Settings")
    limit = s.max_requests_per_user_per_day or 0
    if limit <= 0:
        return
    today = frappe.utils.today()
    count = frappe.db.count("AI Office Analysis Job", {
        "requested_by": frappe.session.user,
        "request_date": [">=", today],
    })
    if count >= limit:
        frappe.throw(_("Bạn đã đạt giới hạn {0} job/ngày.").format(limit))
