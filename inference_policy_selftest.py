#!/usr/bin/env python3
"""Offline contract test for the internal inference budget policy."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "custom_addons", "ai_gateway", "models"))
from inference_config import InferenceBudget, classify_request  # noqa: E402


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print("PASS -", label)


simple = classify_request("وضعیت مرخصی من چیست؟")
reasoning = classify_request("این فاکتور را طبق policy بررسی و برای approval آماده کن")
vision = classify_request("این تصویر چه چیزی را نشان می‌دهد؟", has_attachment=True)
check(simple.purpose == "chat" and simple.max_output_tokens == 1024, "simple requests get the fast chat budget")
check(reasoning.purpose == "reasoning" and reasoning.requires_tools, "business decisions get the reasoning budget")
check(vision.purpose == "vision" and vision.requires_vision, "visual requests get the vision budget")
try:
    InferenceBudget(max_output_tokens=0)
except ValueError:
    print("PASS - unsafe output budget is rejected")
else:
    raise AssertionError("unsafe output budget was accepted")
print("INFERENCE POLICY SELF-TEST PASS")
