from odoo import models


class LLMThreadAllowUploads(models.Model):
    _inherit = "llm.thread"

    # Every extension read_attached_file (file_reader.py) knows how to
    # handle. Anything ending in one of these is removed from the
    # "unsupported" list so the upload isn't blocked before the tool
    # ever sees it. Images were missing here before - the tool could
    # already OCR them, but the attachment never reached it because
    # the upload itself was rejected first with "This model does not
    # support images".
    # The canonical policy lives in ai_gateway, which depends on this module.
    # Resolve it lazily to avoid a manifest dependency cycle during registry
    # bootstrap; the fallback keeps a partial installation fail-closed.
    _ALLOWED_EXTENSIONS = (
        ".txt", ".md", ".csv", ".json", ".html", ".htm", ".pdf",
        ".docx", ".xlsx", ".pptx", ".png", ".jpg", ".jpeg", ".webp",
        ".bmp", ".tif", ".tiff",
    )

    def _check_unsupported_attachments(self, message=None):
        unsupported = super()._check_unsupported_attachments(message)
        allowed = self._ALLOWED_EXTENSIONS
        try:
            from odoo.addons.ai_gateway.controllers.file_policy import ALLOWED_EXTENSIONS
            allowed = tuple(sorted(ALLOWED_EXTENSIONS))
        except (ImportError, AttributeError):
            pass
        return [
            u for u in unsupported
            if not u.get("name", "").lower().endswith(allowed)
        ]
