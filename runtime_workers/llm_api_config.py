"""Compatibility shim - the real module lives inside the ``ai_gateway`` addon.

``llm_api_config`` is pure Python (no Odoo import) because two very different
callers need it:

  * the Odoo addon, for ``/api/admin/llm-provider`` - imported normally as
    ``odoo.addons.ai_gateway.models.llm_api_config``
  * ``runtime_workers/verify_llm_api.py`` and ``seed_api_inference.py``, which
    run under plain ``python3`` with no Odoo on ``sys.path``

Keeping one copy avoids the drift that two copies would cause. The runtime
workers import it through this shim, which resolves the addon file by its
fixed position in the checkout rather than by package path.
"""
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or os.getcwd()))
_CANDIDATES = [
    os.path.join(_HERE, os.pardir, "custom_addons", "ai_gateway", "models", "llm_api_config.py"),
]
_override = os.environ.get("AIBOX_REPO")
if _override:
    _CANDIDATES.insert(
        0,
        os.path.join(_override, "custom_addons", "ai_gateway", "models", "llm_api_config.py"),
    )

_target = None
for _candidate in _CANDIDATES:
    _candidate = os.path.normpath(_candidate)
    if os.path.exists(_candidate):
        _target = _candidate
        break

if _target is None:
    raise ImportError(
        "cannot locate custom_addons/ai_gateway/models/llm_api_config.py; set AIBOX_REPO "
        "to the repository checkout (searched: %s)" % ", ".join(_CANDIDATES)
    )

_spec = importlib.util.spec_from_file_location("_aibox_llm_api_config", _target)
_module = importlib.util.module_from_spec(_spec)
# Registering before exec_module is required, not optional: @dataclass resolves
# string annotations through sys.modules[cls.__module__], so executing the
# module while it is unregistered raises AttributeError: 'NoneType' object has
# no attribute '__dict__'.
import sys as _sys  # noqa: E402
_sys.modules[_spec.name] = _module
try:
    _spec.loader.exec_module(_module)
except BaseException:
    _sys.modules.pop(_spec.name, None)
    raise

# Re-export the public surface so `from runtime_workers.llm_api_config import X`
# keeps working unchanged for both callers.
PROVIDERS = _module.PROVIDERS
LlmEndpoint = _module.LlmEndpoint
LlmApiConfig = _module.LlmApiConfig
detect_provider = _module.detect_provider
normalize_base_url = _module.normalize_base_url
load_config = _module.load_config
default_config = _module.default_config
resolve_key = _module._resolve_key
redact_key = _module._redact
# Existing callers (seed_api_inference.py, verify_llm_api.py) import the
# underscore names; keep both spellings working.
_resolve_key = _module._resolve_key
_redact = _module._redact

__all__ = [
    "PROVIDERS", "LlmEndpoint", "LlmApiConfig", "detect_provider",
    "normalize_base_url", "load_config", "default_config",
    "resolve_key", "redact_key",
]
