import frappe
from frappe.model.document import Document


class AIOfficeSettings(Document):
    """Single DocType — cấu hình LLM, security, storage cho VN Office AI."""

    def validate(self):
        self._validate_timeout()

    def _validate_timeout(self):
        if self.request_timeout_seconds and self.request_timeout_seconds < 10:
            frappe.throw("Timeout tối thiểu 10 giây.")
