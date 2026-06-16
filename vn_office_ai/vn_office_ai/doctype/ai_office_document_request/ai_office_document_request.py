import frappe
from frappe import _
from frappe.model.document import Document


class AIOfficeDocumentRequest(Document):
    """Transaction (submittable) — 1 lần soạn tài liệu Tier 1.

    Lifecycle status (docstatus=0): Draft → Asking Questions → Ready to Generate
        → Generating → Generated/Failed.
    Submit (0→1): chỉ khi status='Generated' + có generated_file; đính kèm vào source.
    """

    # ───────────────────────── validate ─────────────────────────
    def validate(self):
        self._sync_status_from_answers()

    def _sync_status_from_answers(self):
        """Tự nâng status Draft → Ready to Generate khi đủ field bắt buộc."""
        if self.docstatus != 0:
            return
        if self.status in ("Generating", "Generated", "Failed"):
            return
        if not self.template:
            return
        missing = self.get_missing_required_fields()
        self.status = "Ready to Generate" if not missing else "Asking Questions"

    def get_missing_required_fields(self) -> list:
        """Trả về list field_name bắt buộc nhưng chưa có giá trị."""
        tpl = frappe.get_cached_doc("AI Office Template", self.template)
        answered = {fv.field_name: (fv.value_text or "").strip() for fv in self.field_values}
        missing = []
        for q in tpl.questions:
            if q.is_required and not answered.get(q.field_name):
                missing.append(q.field_name)
        return missing

    @frappe.whitelist()
    def get_values_dict(self) -> dict:
        """Trả {field_name: value_text} — dùng trong Print Format Jinja (Tier 1).

        Tránh phải mutate dict trong Jinja sandbox.
        """
        return {fv.field_name: (fv.value_text or "") for fv in self.field_values}

    # ───────────────────────── submit guards ─────────────────────────
    def before_submit(self):
        if self.status != "Generated":
            frappe.throw(_("Phải tạo bản xem trước (status = Generated) trước khi lưu chính thức."))
        if not self.generated_file:
            frappe.throw(_("Chưa có file output để lưu."))

    def on_submit(self):
        self.db_set("attached_to_source", 0)
        if self.source_docname and self.source_doctype:
            self._attach_file_to_source()

    def _attach_file_to_source(self):
        """Đính kèm generated_file vào source record (qua File DocType)."""
        if not frappe.has_permission(self.source_doctype, "read", self.source_docname):
            frappe.throw(_("Bạn không có quyền truy cập record nguồn {0}").format(self.source_docname))

        # Tìm File đang gắn vào Document Request này
        file_url = self.generated_file
        existing = frappe.db.get_value(
            "File", {"file_url": file_url, "attached_to_doctype": self.doctype, "attached_to_name": self.name}
        )
        if existing:
            # Tạo bản sao link sang source (giữ file gốc, thêm attachment cho source)
            src_file = frappe.get_doc({
                "doctype": "File",
                "file_url": file_url,
                "file_name": file_url.split("/")[-1],
                "attached_to_doctype": self.source_doctype,
                "attached_to_name": self.source_docname,
                "folder": "Home/Attachments",
                "is_private": frappe.db.get_value("File", existing, "is_private") or 0,
            })
            src_file.insert(ignore_permissions=True)
            self.db_set("attached_to_source", 1)

    def on_cancel(self):
        """Gỡ attachment khỏi source (giữ File DocType, không xóa thật)."""
        if self.attached_to_source and self.source_docname:
            frappe.db.delete("File", {
                "file_url": self.generated_file,
                "attached_to_doctype": self.source_doctype,
                "attached_to_name": self.source_docname,
            })
            self.db_set("attached_to_source", 0)


# ═══════════════════════════ Hook functions (doc_events) ═══════════════════════════
# Frappe gọi các hàm này theo cấu hình hooks.py.

def validate_request(doc, method=None):
    doc.validate()


def before_submit_request(doc, method=None):
    doc.before_submit()


def on_submit_request(doc, method=None):
    doc.on_submit()


def on_cancel_request(doc, method=None):
    doc.on_cancel()
