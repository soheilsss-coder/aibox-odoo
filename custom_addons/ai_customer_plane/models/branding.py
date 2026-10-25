import base64
import json
import re
from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.exceptions import ValidationError


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ASSET_MAX_BYTES = 4 * 1024 * 1024


class AiCustomerBranding(models.Model):
    """Company-scoped source of truth for customer white-label settings.

    The browser never writes arbitrary CSS or configuration parameters. Brand
    values are explicit, validated fields so a customer appliance can be
    migrated, audited and rolled back as one versioned record.
    """

    _name = "ai.customer.branding"
    _description = "Customer White-label Branding"
    _order = "company_id"

    company_id = fields.Many2one(
        "res.company", required=True, index=True, ondelete="restrict",
        default=lambda self: self.env.company,
    )

    # Identity and customer-facing copy.
    brand_name = fields.Char(required=True, default="Company AI", size=200)
    legal_name = fields.Char(size=200)
    tagline = fields.Char(size=300)
    product_title = fields.Char(size=200)
    brand_domain = fields.Char(size=500)
    support_email = fields.Char(size=254)
    support_url = fields.Char(size=500)
    footer_text = fields.Char(size=500)
    login_message = fields.Text()

    # Uploaded assets are stored as attachments, never in a JSON parameter.
    logo = fields.Binary(attachment=True)
    logo_filename = fields.Char(size=255)
    logo_mimetype = fields.Char(size=100)
    favicon = fields.Binary(attachment=True)
    favicon_filename = fields.Char(size=255)
    favicon_mimetype = fields.Char(size=100)

    # Theme tokens. Values are deliberately constrained to six-digit hex.
    primary_color = fields.Char(required=True, default="#4f8cff", size=7)
    secondary_color = fields.Char(required=True, default="#8b5cf6", size=7)
    accent_color = fields.Char(required=True, default="#3dd68c", size=7)
    background_color = fields.Char(required=True, default="#0f1115", size=7)
    surface_color = fields.Char(required=True, default="#171a21", size=7)
    surface_alt_color = fields.Char(required=True, default="#1e222b", size=7)
    text_color = fields.Char(required=True, default="#e8eaed", size=7)
    text_muted_color = fields.Char(required=True, default="#9aa1ac", size=7)
    danger_color = fields.Char(required=True, default="#e5484d", size=7)
    warning_color = fields.Char(required=True, default="#caa23d", size=7)

    font_family = fields.Selection([
        ("system", "System"),
        ("vazirmatn", "Vazirmatn"),
        ("inter", "Inter"),
    ], required=True, default="system")
    border_radius = fields.Selection([
        ("compact", "Compact"),
        ("comfortable", "Comfortable"),
        ("rounded", "Rounded"),
    ], required=True, default="comfortable")

    # Experience switches are explicit feature flags, not arbitrary frontend
    # settings. Authorization is still enforced by backend endpoints.
    show_ai_brand = fields.Boolean(default=True)
    show_powered_by = fields.Boolean(default=False)
    show_module_navigation = fields.Boolean(default=True)
    support_contact_visible = fields.Boolean(default=True)

    active = fields.Boolean(default=True, index=True)
    version = fields.Integer(default=1, required=True, readonly=True)
    updated_by_id = fields.Many2one("res.users", readonly=True)
    updated_at = fields.Datetime(readonly=True)

    _COLOR_FIELDS = {
        "primary_color", "secondary_color", "accent_color", "background_color",
        "surface_color", "surface_alt_color", "text_color", "text_muted_color",
        "danger_color", "warning_color",
    }
    _MUTABLE_FIELDS = {
        "company_id", "brand_name", "legal_name", "tagline", "product_title",
        "brand_domain", "support_email", "support_url", "footer_text",
        "login_message", "logo", "logo_filename", "logo_mimetype", "favicon",
        "favicon_filename", "favicon_mimetype", "primary_color", "secondary_color",
        "accent_color", "background_color", "surface_color", "surface_alt_color",
        "text_color", "text_muted_color", "danger_color", "warning_color",
        "font_family", "border_radius", "show_ai_brand", "show_powered_by",
        "show_module_navigation", "support_contact_visible", "active",
    }

    _sql_constraints = [
        (
            "company_unique",
            "unique(company_id)",
            "Only one customer branding record is allowed per company.",
        ),
    ]

    @api.model
    def get_for_company(self, company=None):
        """Return the existing record without creating data during a read."""
        company = company or self.env.company
        return self.search([("company_id", "=", company.id), ("active", "=", True)], limit=1)

    @api.model
    def create_default_for_company(self, company=None):
        company = company or self.env.company
        existing = self.search([("company_id", "=", company.id)], limit=1)
        if existing:
            return existing
        return self.create({
            "company_id": company.id,
            "brand_name": company.name or "Company AI",
            "legal_name": company.name or False,
        })

    @api.model
    def _validate_hex(self, value, label):
        if not isinstance(value, str) or not _HEX_COLOR.fullmatch(value):
            raise ValidationError("%s must be a six-digit hexadecimal color." % label)
        return value.lower()

    @api.model
    def _validate_url(self, value, label):
        if not value:
            return
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValidationError("%s must be an http or https URL." % label)

    @api.model
    def _validate_asset(self, value, label):
        if not value:
            return
        try:
            raw = base64.b64decode(value, validate=False)
        except (TypeError, ValueError) as exc:
            raise ValidationError("%s contains invalid binary data." % label) from exc
        if len(raw) > _ASSET_MAX_BYTES:
            raise ValidationError("%s exceeds the 4 MB limit." % label)

    @api.constrains(
        "brand_name", "brand_domain", "support_email", "support_url",
        "primary_color", "secondary_color", "accent_color", "background_color",
        "surface_color", "surface_alt_color", "text_color", "text_muted_color",
        "danger_color", "warning_color", "logo", "favicon",
    )
    def _check_brand_contract(self):
        for record in self:
            if not (record.brand_name or "").strip():
                raise ValidationError("Brand name is required.")
            for field_name in self._COLOR_FIELDS:
                record._validate_hex(getattr(record, field_name), field_name)
            record._validate_url(record.brand_domain, "Brand domain")
            record._validate_url(record.support_url, "Support URL")
            if record.support_email and not _EMAIL.fullmatch(record.support_email.strip()):
                raise ValidationError("Support email is invalid.")
            if len(record.login_message or "") > 2000:
                raise ValidationError("Login message exceeds the 2000 character limit.")
            record._validate_asset(record.logo, "Logo")
            record._validate_asset(record.favicon, "Favicon")

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            vals.setdefault("company_id", self.env.company.id)
            vals.setdefault("updated_by_id", self.env.user.id)
            vals.setdefault("updated_at", now)
        records = super().create(vals_list)
        records._check_brand_contract()
        return records

    def write(self, vals):
        vals = dict(vals)
        if self._MUTABLE_FIELDS.intersection(vals):
            vals["version"] = max(self.mapped("version") or [1]) + 1
            vals["updated_by_id"] = self.env.user.id
            vals["updated_at"] = fields.Datetime.now()
        result = super().write(vals)
        self._check_brand_contract()
        return result

    def public_values(self, asset_base_url="/api/branding"):
        """Return only safe values suitable for an authenticated product UI."""
        self.ensure_one()
        return {
            "brand_name": self.brand_name,
            "product_title": self.product_title or self.brand_name,
            "tagline": self.tagline or "",
            "brand_domain": self.brand_domain or "",
            "footer_text": self.footer_text or "",
            "login_message": self.login_message or "",
            "support_email": self.support_email if self.support_contact_visible else "",
            "support_url": self.support_url if self.support_contact_visible else "",
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "accent_color": self.accent_color,
            "background_color": self.background_color,
            "surface_color": self.surface_color,
            "surface_alt_color": self.surface_alt_color,
            "text_color": self.text_color,
            "text_muted_color": self.text_muted_color,
            "danger_color": self.danger_color,
            "warning_color": self.warning_color,
            "font_family": self.font_family,
            "border_radius": self.border_radius,
            "show_ai_brand": self.show_ai_brand,
            "show_powered_by": self.show_powered_by,
            "show_module_navigation": self.show_module_navigation,
            "support_contact_visible": self.support_contact_visible,
            "version": self.version,
            "logo_url": "%s/logo" % asset_base_url if self.logo else None,
            "favicon_url": "%s/favicon" % asset_base_url if self.favicon else None,
            "has_logo": bool(self.logo),
            "has_favicon": bool(self.favicon),
        }

    def admin_values(self, asset_base_url="/api/branding"):
        self.ensure_one()
        values = self.public_values(asset_base_url=asset_base_url)
        values.update({
            "company_id": self.company_id.id,
            "company_name": self.company_id.name,
            "legal_name": self.legal_name or "",
            "logo_filename": self.logo_filename or "",
            "favicon_filename": self.favicon_filename or "",
            "updated_by": self.updated_by_id.name if self.updated_by_id else None,
            "updated_at": str(self.updated_at) if self.updated_at else None,
        })
        return values

    def export_snapshot(self):
        """Stable, binary-free snapshot for audit and setup evidence."""
        self.ensure_one()
        values = self.public_values()
        values.update({
            "company_id": self.company_id.id,
            "version": self.version,
            "has_logo": bool(self.logo),
            "has_favicon": bool(self.favicon),
        })
        return json.loads(json.dumps(values, sort_keys=True, ensure_ascii=False))
