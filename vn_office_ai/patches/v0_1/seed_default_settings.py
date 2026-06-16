"""Patch (post_model_sync) — set default AI Office Settings. Idempotent."""

from vn_office_ai.install import create_default_settings


def execute():
    create_default_settings()
