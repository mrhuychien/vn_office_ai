import frappe
import json
from frappe.model.document import Document


class AIOfficeTemplate(Document):
    """Master — định nghĩa 1 template Tier 1 (câu hỏi + prompt + cách render output)."""

    def validate(self):
        self._validate_source_filter_json()
        self._validate_render_engine()
        self._validate_question_field_names()

    def _validate_source_filter_json(self):
        if self.source_filter:
            try:
                json.loads(self.source_filter)
            except json.JSONDecodeError:
                frappe.throw("Filter nguồn phải là JSON hợp lệ.")

    def _validate_render_engine(self):
        if self.render_engine == "Print Format" and not self.print_format:
            frappe.throw("Render bằng Print Format thì phải chọn Print Format.")

    def _validate_question_field_names(self):
        seen = set()
        for q in self.questions:
            if q.field_name in seen:
                frappe.throw(f"Field name trùng: {q.field_name}")
            seen.add(q.field_name)
            if " " in (q.field_name or ""):
                frappe.throw(f"Field name không được chứa khoảng trắng: {q.field_name}")
