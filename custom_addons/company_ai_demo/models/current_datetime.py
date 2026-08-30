from datetime import datetime

from odoo import models
from odoo.addons.llm_tool.decorators import llm_tool

try:
    import jdatetime
    HAS_JDATETIME = True
except ImportError:
    HAS_JDATETIME = False


class LLMToolCurrentDateTime(models.Model):
    _inherit = "llm.tool"

    @llm_tool(read_only_hint=True)
    def get_current_datetime(self) -> dict:
        """Get the current real date and time from the server, in both
        Gregorian and Persian (Jalali) calendars. ALWAYS use this tool
        for any question about today's date - never calculate or guess
        the Jalali date yourself from memory, use the values returned
        here exactly, they are computed by a reliable library."""
        now = datetime.now()
        result = {
            "gregorian_date": now.strftime("%Y-%m-%d"),
            "day_of_week": now.strftime("%A"),
            "time": now.strftime("%H:%M:%S"),
        }
        if HAS_JDATETIME:
            jnow = jdatetime.datetime.fromgregorian(datetime=now)
            result["jalali_date"] = jnow.strftime("%Y-%m-%d")
            result["jalali_date_fa"] = jnow.strftime("%d %B %Y")
        else:
            result["jalali_date"] = "jdatetime package not installed - only Gregorian available"
        return result
