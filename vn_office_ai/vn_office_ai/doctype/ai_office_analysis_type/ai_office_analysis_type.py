import frappe
import json
from frappe.model.document import Document


class AIOfficeAnalysisType(Document):
    """Master — định nghĩa 1 loại nghiệp vụ AI Analyst (Tier 2)."""

    def validate(self):
        self._validate_finding_schema()
        self._validate_output()
        self._validate_query_mode()

    def _validate_finding_schema(self):
        if self.finding_schema:
            try:
                json.loads(self.finding_schema)
            except json.JSONDecodeError:
                frappe.throw("Finding Schema phải là JSON hợp lệ.")

    def _validate_output(self):
        if self.output_action == "Create Draft":
            if not self.output_doctype:
                frappe.throw("Action 'Create Draft' yêu cầu Output DocType.")
            if not self.output_mapping_jinja:
                frappe.throw("Action 'Create Draft' yêu cầu Output Mapping.")

    def _validate_query_mode(self):
        if self.input_mode in ("Internal Query Only", "Both") and not self.query_definition:
            frappe.throw("Input mode cần query nội bộ nhưng Query Definition đang trống.")
