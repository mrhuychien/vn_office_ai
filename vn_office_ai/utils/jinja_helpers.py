"""Jinja helpers cho Print Format Tier 1 (đăng ký ở hooks.jinja.methods)."""

import frappe

_ONES = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_UNITS = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ"]


def format_vnd(value) -> str:
    """Định dạng số tiền VND có dấu chấm phân cách nghìn. VD 1500000 → '1.500.000'."""
    try:
        return "{:,.0f}".format(float(value or 0)).replace(",", ".")
    except (ValueError, TypeError):
        return "0"


def so_tien_bang_chu(value) -> str:
    """Đọc số tiền thành chữ tiếng Việt. VD 1500000 → 'Một triệu năm trăm nghìn đồng'.

    Hỗ trợ tới hàng nghìn tỷ. Làm tròn về số nguyên đồng.
    """
    try:
        n = int(round(float(value or 0)))
    except (ValueError, TypeError):
        return ""
    if n == 0:
        return "Không đồng"

    groups = []
    while n > 0:
        groups.append(n % 1000)
        n //= 1000

    parts = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        chunk = _read_three_digits(g, full=(i != len(groups) - 1))
        unit = _UNITS[i] if i < len(_UNITS) else ""
        parts.append((chunk + " " + unit).strip())

    text = " ".join(parts).strip()
    text = text[0].upper() + text[1:]
    return text + " đồng"


def _read_three_digits(num, full=False):
    """Đọc 1 nhóm 3 chữ số. full=True buộc đọc 'không trăm' khi đứng giữa."""
    hundred = num // 100
    ten = (num % 100) // 10
    one = num % 10
    words = []

    if hundred > 0 or full:
        words.append(_ONES[hundred] + " trăm")

    if ten == 0:
        if one > 0 and (hundred > 0 or full):
            words.append("lẻ " + _ONES[one])
        elif one > 0:
            words.append(_ONES[one])
    elif ten == 1:
        words.append("mười")
        if one == 5:
            words.append("lăm")
        elif one > 0:
            words.append(_ONES[one])
    else:
        words.append(_ONES[ten] + " mươi")
        if one == 1:
            words.append("mốt")
        elif one == 5:
            words.append("lăm")
        elif one > 0:
            words.append(_ONES[one])

    return " ".join(words).strip()
