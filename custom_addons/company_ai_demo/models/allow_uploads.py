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
    _ALLOWED_EXTENSIONS = (
        ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
        ".csv", ".txt", ".html", ".htm",
        ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
    )

    def _check_unsupported_attachments(self, message=None):
        unsupported = super()._check_unsupported_attachments(message)
        return [
            u for u in unsupported
            if not u.get("name", "").lower().endswith(self._ALLOWED_EXTENSIONS)
        ]
