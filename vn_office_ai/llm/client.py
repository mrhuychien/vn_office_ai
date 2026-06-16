"""OpenRouter client wrapper cho VN Office AI.

Đọc API key (encrypted) + model từ AI Office Settings. Trả về dict chuẩn hoá
gồm text, token usage, cost ước tính, duration.
"""

import time
import json

import frappe
import requests

# USD / 1M tokens (input, output) — fallback khi OpenRouter không trả usage.cost.
# Cập nhật định kỳ theo bảng giá OpenRouter.
OPENROUTER_PRICING = {
    "google/gemini-2.5-flash": (0.30, 2.50),
    "anthropic/claude-haiku-4.5": (1.00, 5.00),
    "anthropic/claude-sonnet-4.7": (3.00, 15.00),
}


class LLMError(frappe.ValidationError):
    pass


def get_settings():
    s = frappe.get_cached_doc("AI Office Settings")
    if not s.enabled:
        frappe.throw("AI Office đang tắt. Liên hệ quản trị viên.")
    return s


def chat_completion(messages, *, model=None, max_tokens=None,
                    response_format=None, purpose="document"):
    """Gọi OpenRouter chat completions.

    Args:
        messages: list[{"role": "system"|"user"|"assistant", "content": str}]
        model: override model; None = dùng default/analyst model theo purpose
        max_tokens: override; None = dùng Settings
        response_format: {"type": "json_object"} cho structured output (Tier 2)
        purpose: "document" (Tier 1) | "analyst" (Tier 2)

    Returns:
        dict: text, input_tokens, output_tokens, cost_usd, duration_ms, model, raw
    """
    s = get_settings()
    model = model or (s.analyst_model if purpose == "analyst" else s.default_model)

    if s.allowed_models:
        allowed = [m.strip() for m in s.allowed_models.splitlines() if m.strip()]
        if model not in allowed:
            frappe.throw(f"Model {model} không nằm trong whitelist.")

    api_key = s.get_password("openrouter_api_key")
    if not api_key:
        frappe.throw("Chưa cấu hình OpenRouter API Key trong AI Office Settings.")

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens or s.max_tokens_per_request or 8000,
    }
    if response_format:
        payload["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": frappe.utils.get_url(),
        "X-Title": "VN Office AI",
    }

    base_url = (s.openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
    timeout = s.request_timeout_seconds or 120

    t0 = time.monotonic()
    try:
        resp = requests.post(f"{base_url}/chat/completions",
                             headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        raise LLMError("LLM timeout — thử lại hoặc giảm phạm vi dữ liệu.")
    except requests.exceptions.HTTPError:
        raise LLMError(f"OpenRouter lỗi {resp.status_code}: {resp.text[:300]}")
    except requests.exceptions.RequestException as e:
        raise LLMError(f"Lỗi kết nối OpenRouter: {e}")

    duration_ms = int((time.monotonic() - t0) * 1000)
    data = resp.json()

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise LLMError(f"Phản hồi OpenRouter không hợp lệ: {json.dumps(data)[:300]}")

    usage = data.get("usage", {}) or {}
    in_tok = usage.get("prompt_tokens", 0)
    out_tok = usage.get("completion_tokens", 0)

    return {
        "text": text,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": _estimate_cost(model, in_tok, out_tok, usage),
        "duration_ms": duration_ms,
        "model": model,
        "raw": data if s.log_full_response else None,
    }


def analyst_completion(system_prompt, data_payload, finding_schema):
    """Tier 2 helper — ép LLM trả JSON theo finding_schema (dùng ở Phase 3)."""
    user_msg = (
        "Dữ liệu cần phân tích:\n```json\n"
        + json.dumps(data_payload, ensure_ascii=False)
        + "\n```\n\nTrả về DUY NHẤT một JSON object đúng schema sau, "
        + "không markdown, không giải thích:\n```json\n"
        + finding_schema + "\n```"
    )
    res = chat_completion(
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": user_msg}],
        purpose="analyst",
        response_format={"type": "json_object"},
    )
    raw = res["text"].strip()
    if raw.startswith("```"):
        # bỏ fence ```json ... ```
        raw = raw.split("```")[1]
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    res["parsed"] = json.loads(raw)
    return res


def _estimate_cost(model, in_tok, out_tok, usage):
    if usage.get("cost"):
        return round(float(usage["cost"]), 6)
    pin, pout = OPENROUTER_PRICING.get(model, (0, 0))
    return round((in_tok * pin + out_tok * pout) / 1_000_000, 6)
