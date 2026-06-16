"""Xây prompt cho Tier 1 (document generation).

Ghép system prompt của template + câu trả lời của user (đã che PII narrative)
thành messages gửi LLM. AI trả về HTML body hoàn chỉnh.
"""

import frappe

from vn_office_ai.llm import pii


def build_document_prompt(doc) -> list:
    """Tạo messages [{role, content}] từ AI Office Document Request.

    Args:
        doc: AI Office Document Request document

    Returns:
        list messages cho chat_completion
    """
    tpl = frappe.get_cached_doc("AI Office Template", doc.template)

    # Gom field values thành bảng dữ liệu cho AI
    lines = []
    for fv in doc.field_values:
        val = (fv.value_text or "").strip()
        if not val:
            continue
        # Che PII trong giá trị tự do (tên, địa chỉ...) nhưng giữ field mã nếu cần.
        # Mặc định che tất cả value; field mã chứng từ ở Tier 1 hiếm khi nhạy cảm.
        masked = pii.mask(val)
        lines.append(f"- {fv.field_label or fv.field_name}: {masked}")

    data_block = "\n".join(lines) if lines else "(không có dữ liệu)"

    user_content = (
        "Dưới đây là thông tin để soạn tài liệu. Hãy tạo tài liệu hoàn chỉnh "
        "theo đúng yêu cầu trong hướng dẫn hệ thống.\n\n"
        f"{data_block}\n\n"
        "Lưu ý: dùng {{COMPANY}} làm placeholder cho tên công ty nếu chưa được cung cấp. "
        "Trả về DUY NHẤT nội dung HTML, không kèm giải thích hay markdown."
    )

    return [
        {"role": "system", "content": tpl.prompt_system},
        {"role": "user", "content": user_content},
    ]
