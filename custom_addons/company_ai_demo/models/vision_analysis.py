import base64
import logging

import requests
from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)

# Separate vLLM instance running a vision-capable model, started with
# start_vllm_vision.sh (see setup script) on a different port so it
# doesn't compete with the main text model process.
#
# Roadmap item #17 (Model Registry): this used to be the only place
# the vision endpoint was defined, which meant changing it required a
# code change + module upgrade. It's now only the fallback used if
# the ir.config_parameter below is ever missing (e.g. right after
# `odoo -i` on a brand new DB, before data/vision_config_data.xml has
# loaded, or if someone manually deletes the parameter) - the value
# actually used day-to-day is company_ai_demo.vision_api_base, set in
# data/vision_config_data.xml and editable from Settings > Technical >
# System Parameters with no code change or restart needed.
VISION_API_BASE = "http://127.0.0.1:8001/v1"
VISION_API_BASE_PARAM = "company_ai_demo.vision_api_base"


class LLMToolVisionAnalysis(models.Model):
    _inherit = "llm.tool"

    def _vision_api_base(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            VISION_API_BASE_PARAM, VISION_API_BASE
        )

    @llm_tool(read_only_hint=True)
    def analyze_image(self, question: str) -> dict:
        """Analyze the most recently attached IMAGE using a vision-
        capable AI model - for general visual questions that have
        nothing to do with company data, e.g. reading an architectural
        drawing, estimating materials from a blueprint, describing a
        photo, reading a diagram. This is different from
        read_attached_file (which is for text extraction from
        documents/scanned pages) - use this one when the user wants the
        model to actually reason about what's IN the image, not just
        transcribe text from it.

        Parameters:
            question: What to ask about the image (e.g. 'چقدر میلگرد
                برای این نقشه لازمه؟').
        """
        current_message = self.env.context.get("message")
        if not current_message or current_message.model != "llm.thread":
            return {"error": "Could not determine the current chat thread."}

        thread_id = current_message.res_id
        messages = self.env["mail.message"].search(
            [("model", "=", "llm.thread"), ("res_id", "=", thread_id)],
            order="create_date desc",
        )
        attachments = messages.mapped("attachment_ids").filtered(
            lambda a: (a.mimetype or "").startswith("image/")
        )
        if not attachments:
            return {"error": "No attached image found in this conversation."}

        attachment = attachments[0]
        image_b64 = base64.b64encode(attachment.raw).decode("utf-8")
        mimetype = attachment.mimetype or "image/png"

        try:
            resp = requests.post(
                f"{self._vision_api_base()}/chat/completions",
                json={
                    "model": self.env["ai.model.router"].route(purpose="vision").model_id,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": question},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mimetype};base64,{image_b64}"
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 1024,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            return {"filename": attachment.name, "analysis": answer}
        except requests.exceptions.ConnectionError:
            return {
                "error": "Vision model is not running. Start it with "
                         "/opt/start_vllm_vision.sh on the server first."
            }
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Vision analysis failed: %s", exc)
            return {"error": "Vision analysis failed, try again shortly"}
