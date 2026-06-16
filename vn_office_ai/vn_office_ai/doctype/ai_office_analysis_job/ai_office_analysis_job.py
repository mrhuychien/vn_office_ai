import frappe
from frappe import _
from frappe.model.document import Document


# Trạng thái finding tính là "đã xử lý" (không còn Pending)
_DECIDED = ("Approved", "Rejected", "Modified", "Skipped")


class AIOfficeAnalysisJob(Document):
    """Transaction (submittable) — 1 lần phân tích AI Analyst.

    Lifecycle (docstatus 0): Draft → Uploading → Analyzing → Ready For Review
        → Under Review → Ready To Commit → Committed → (Submitted khi docstatus 1).
    Review từng finding = field write permlevel 1 (chỉ reviewer). Submit khi mọi
    approved/modified finding đã committed=1.
    """

    def validate(self):
        self._validate_period()
        self.recompute_counters()
        self._auto_transition_status()

    def _validate_period(self):
        if self.period_from and self.period_to and self.period_from > self.period_to:
            frappe.throw(_("Từ ngày phải ≤ Đến ngày."))

    # ───────────────────────── counters + status ─────────────────────────
    def recompute_counters(self):
        total = len(self.findings)
        approved = sum(1 for f in self.findings if f.review_status == "Approved")
        rejected = sum(1 for f in self.findings if f.review_status == "Rejected")
        modified = sum(1 for f in self.findings if f.review_status == "Modified")
        skipped = sum(1 for f in self.findings if f.review_status == "Skipped")
        pending = sum(1 for f in self.findings if f.review_status == "Pending")
        critical = sum(1 for f in self.findings if f.severity == "Critical")

        self.total_findings = total
        self.approved_findings = approved
        self.rejected_findings = rejected
        self.modified_findings = modified
        self.pending_findings = pending
        self.critical_findings = critical
        # skipped không có counter riêng (gộp vào "đã xử lý")

    def _auto_transition_status(self):
        """Tự chuyển status theo tiến độ review (chỉ khi docstatus=0 và đã có findings)."""
        if self.docstatus != 0:
            return
        # Không can thiệp các status do code/background điều khiển
        if self.status in ("Draft", "Uploading", "Analyzing", "Failed", "Committed"):
            return
        if self.total_findings == 0:
            return

        decided = sum(1 for f in self.findings if f.review_status in _DECIDED)
        if self.pending_findings == 0:
            self.status = "Ready To Commit"
        elif decided > 0:
            self.status = "Under Review"
        else:
            self.status = "Ready For Review"

    # ───────────────────────── submit / cancel ─────────────────────────
    def before_submit(self):
        self.recompute_counters()
        if self.status != "Committed":
            frappe.throw(_("Chỉ hoàn tất (submit) được khi job đã ở trạng thái Committed."))
        if self.pending_findings != 0:
            frappe.throw(_("Còn {0} đề xuất chưa duyệt.").format(self.pending_findings))
        # Mọi finding Approved/Modified phải đã tạo chứng từ thành công
        not_committed = [
            f.finding_no for f in self.findings
            if f.review_status in ("Approved", "Modified") and not f.committed
        ]
        if not_committed:
            frappe.throw(_("Các đề xuất sau chưa tạo được chứng từ: {0}").format(", ".join(not_committed)))

    def on_cancel(self):
        """Chain-safe: chặn cancel nếu còn output đã Submitted."""
        submitted = [
            o.output_docname for o in self.output_documents if o.status == "Submitted"
        ]
        if submitted:
            frappe.throw(_("Phải hủy các chứng từ đã ghi sổ trước: {0}").format(", ".join(submitted)))
        self.db_set("status", "Failed")


# ═══════════════════════════ Hook functions (doc_events) ═══════════════════════════

def validate_job(doc, method=None):
    doc.validate()


def before_submit_job(doc, method=None):
    doc.before_submit()


def on_submit_job(doc, method=None):
    # Job submitted = audit lock. Không tạo thêm gì (output đã tạo ở bước Commit).
    pass


def on_cancel_job(doc, method=None):
    doc.on_cancel()
