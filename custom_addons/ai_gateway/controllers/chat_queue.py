"""Compatibility shim: the chat capacity pool lives in
``ai_gateway/models/chat_queue.py``; this controller-level import path is
kept because the gateway controller (and third-party integrations) import
it from here. Delegates - never duplicates - so there is exactly one
queue implementation in the process.
"""
from odoo.addons.ai_gateway.models.chat_queue import get_chat_pool  # noqa: F401

__all__ = ["get_chat_pool"]
