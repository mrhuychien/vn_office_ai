"""Che PII (CCCD/CMND, MST, STK ngân hàng, SĐT) trước khi gửi LLM.

Chỉ áp lên VĂN BẢN TỰ DO (narrative), KHÔNG áp lên key field như số chứng từ
(để Tier 2 còn đối chiếu được). Bật/tắt qua Settings.mask_pii_before_llm.
"""

import re

import frappe

# Thứ tự QUAN TRỌNG: pattern cụ thể (12 số, 10 số) trước pattern rộng (STK 8-19 số).
BUILTIN_PATTERNS = [
    (re.compile(r"\b\d{12}\b"), "[CCCD]"),          # Căn cước công dân 12 số
    (re.compile(r"\b\d{10}(?:-\d{3})?\b"), "[MST]"),  # Mã số thuế 10 hoặc 13 số
    (re.compile(r"\b\d{9}\b"), "[CMND]"),            # CMND cũ 9 số
    (re.compile(r"\b(?:0|\+84)\d{9}\b"), "[SĐT]"),   # Số điện thoại VN
    (re.compile(r"\b\d{8,19}\b"), "[STK]"),          # Số tài khoản (rộng, đặt cuối)
]


def mask(text: str) -> str:
    """Che PII trong text nếu Settings bật. An toàn với input None."""
    if not text:
        return text
    s = frappe.get_cached_doc("AI Office Settings")
    if not s.mask_pii_before_llm:
        return text

    patterns = list(BUILTIN_PATTERNS)
    if s.pii_patterns:
        for line in s.pii_patterns.splitlines():
            line = line.strip()
            if line:
                try:
                    patterns.append((re.compile(line), "[REDACTED]"))
                except re.error:
                    frappe.log_error(f"PII pattern lỗi: {line}", "AIO PII")

    for pat, repl in patterns:
        text = pat.sub(repl, text)
    return text
