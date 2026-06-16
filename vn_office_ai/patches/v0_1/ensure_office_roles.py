"""Patch (post_model_sync) — tạo 3 office role. Idempotent."""

from vn_office_ai.install import ensure_office_roles


def execute():
    ensure_office_roles()
