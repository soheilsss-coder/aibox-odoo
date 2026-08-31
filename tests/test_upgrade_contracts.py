"""Pure-Python contract checks for the upgrade work.

These tests deliberately do not import the ERP runtime. They catch the class of
install and registry regressions that previously made the static audit report a
false PASS. Runtime and DGX checks remain separate and are marked as required.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import re
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "custom_addons"


def _module_from_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _file_policy():
    return _module_from_path(
        "upgrade_file_policy", ADDONS / "ai_gateway/controllers/file_policy.py"
    )


def _output_firewall():
    return _module_from_path(
        "upgrade_output_firewall", ADDONS / "ai_gateway/controllers/output_firewall.py"
    )


def xml_records(model_name: str):
    for path in ADDONS.glob("*/data/*.xml"):
        root = ET.parse(path).getroot()
        for record in root.findall(".//record"):
            if record.get("model") != model_name:
                continue
            values = {}
            for field in record.findall("field"):
                if field.get("name") == "name":
                    values["name"] = (field.text or "").strip()
                elif field.get("name") in {"tool_name", "capability_name", "module_name", "handler_key"}:
                    values[field.get("name")] = (field.text or "").strip()
            yield path, record.get("id"), values


class SourceContracts(unittest.TestCase):
    def test_capability_names_are_unique_across_data_files(self):
        rows = list(xml_records("ai.control.capability"))
        names = [values.get("name") for _, _, values in rows]
        duplicates = sorted({name for name in names if name and names.count(name) > 1})
        self.assertEqual(duplicates, [], f"duplicate capability data: {duplicates}")

    def test_unified_operations_have_one_risk_contract(self):
        capabilities = {values.get("name") for _, _, values in xml_records("ai.control.capability")}
        risks = {
            values.get("tool_name")
            for _, _, values in xml_records("ai.gateway.tool.risk")
        }
        operations = [
            values for _, _, values in xml_records("ai.integration.operation")
        ]
        self.assertTrue(operations)
        self.assertEqual(
            sorted(values.get("tool_name") for values in operations if values.get("tool_name") not in risks),
            [],
        )
        self.assertEqual(
            sorted(values.get("capability_name") for values in operations if values.get("capability_name") not in capabilities),
            [],
        )

    def test_authorization_contract_and_delegation_call_match(self):
        auth_source = (ADDONS / "ai_control_plane/models/authorization.py").read_text()
        delegation_source = (ADDONS / "ai_customer_plane/models/delegation.py").read_text()
        auth_tree = ast.parse(auth_source)
        signatures = {
            node.name: [arg.arg for arg in node.args.args]
            for node in ast.walk(auth_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertEqual(
            signatures["check_capability"], ["self", "capability", "user", "record", "action"]
        )
        self.assertIn("user=rec.delegator_id", delegation_source)
        self.assertIn("record=target or None", delegation_source)
        self.assertNotIn("model=rec.resource_model", delegation_source)
        self.assertNotIn("res_id=rec.resource_id", delegation_source)

    def test_readiness_uses_canonical_module_model_and_dynamic_inventory(self):
        source = (ADDONS / "ai_customer_plane/models/customer_config.py").read_text()
        self.assertIn('"ai.control.module"', source)
        self.assertNotIn('"ai.integration.module"', source)
        self.assertIn("unregistered_installed_modules", source)
        self.assertIn("operation_modules", source)
        self.assertIn("operation_coverage", source)
        self.assertIn("uninstalled_operation_modules", source)

    def test_scim_has_exception_import_and_standard_contract_markers(self):
        source = (ADDONS / "ai_customer_plane/models/scim.py").read_text()
        api = (ADDONS / "ai_customer_plane/controllers/scim_api.py").read_text()
        self.assertIn("from odoo.exceptions import ValidationError", source)
        for marker in ("startIndex", "count", "filter", "PATCH", "PUT", "ServiceProviderConfig"):
            self.assertIn(marker, api)
        self.assertIn("SCIM_PATCH_SCHEMA", api)
        sso = (ADDONS / "ai_customer_plane/controllers/sso_api.py").read_text()
        self.assertIn("_provider_url", sso)
        self.assertIn("AI_SSO_PUBLIC_BASE_URL", sso)
        self.assertIn("_sso_allowed", sso)

    def test_unified_handler_keys_are_implemented(self):
        data = [values for _, _, values in xml_records("ai.integration.operation")]
        source = (ADDONS / "ai_integration/models/unified_registry.py").read_text()
        for row in data:
            handler = row.get("handler_key")
            self.assertRegex(source, rf"def _handle_{re.escape(handler)}\(")

    def test_public_output_firewall_and_native_imports(self):
        firewall = (ADDONS / "ai_gateway/controllers/output_firewall.py").read_text()
        gateway = (ADDONS / "ai_gateway/controllers/gateway.py").read_text()
        collab = (ADDONS / "ai_collaboration/models/channel_link.py").read_text()
        scheduled = (ADDONS / "ai_business_tools/models/scheduled_command_tools.py").read_text()
        self.assertIn("scrub_public_text", gateway)
        self.assertIn("odoo.addons.ai_gateway", collab)
        self.assertIn("odoo.addons.ai_gateway", scheduled)
        self.assertIn("enterprise system", firewall)
        self.assertIn("last_seen_message_id", collab)
        self.assertNotIn("from custom_addons", collab + scheduled)
        unified = (ADDONS / "ai_integration/models/unified_registry.py").read_text()
        self.assertNotIn("self.env['hr.employee'].sudo()", unified)
        gate = (ADDONS / "ai_gateway/models/execution_gate.py").read_text()
        self.assertIn("if registry.resolve(tool_name):", gate)
        self.assertIn("registered operation with", gate)

    def test_customer_surfaces_do_not_return_infrastructure_identifiers(self):
        experience = (ADDONS / "ai_experience/controllers/experience_api.py").read_text()
        semantic = (ADDONS / "ai_semantic_api/controllers/semantic_api.py").read_text()
        self.assertNotIn('"provider": m.provider', experience)
        self.assertNotIn('"model_id": m.model_id', experience)
        self.assertNotIn('"provider": a.model_id.provider_id.name', semantic)
        self.assertNotIn('"vision_api_base":', semantic)
        self.assertIn("base64.b64decode(content, validate=True)", semantic)
        self.assertIn('"Content-Type", upload["mimetype"]', semantic)

    def test_public_firewall_scrubs_technical_identifiers(self):
        scrub = _output_firewall().scrub_public_text
        value = scrub("Odoo vLLM Qwen /api/chat Traceback res.users؛ درخواست شما ثبت شد")
        for marker in ("Odoo", "vLLM", "Qwen", "/api/chat", "Traceback", "res.users"):
            self.assertNotIn(marker, value)
        self.assertIn("درخواست شما ثبت شد", value)

    def test_upload_policy_rejects_mismatched_and_unsafe_files(self):
        policy = _file_policy()
        self.assertEqual(policy.validate_upload("notes.txt", b"hello")["mimetype"], "text/plain")
        with self.assertRaises(ValueError):
            policy.validate_upload("notes.pdf", b"not a pdf")
        with self.assertRaises(ValueError):
            policy.validate_upload("notes.exe", b"MZ")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escape.txt", "blocked")
        with self.assertRaises(ValueError):
            policy.validate_upload("document.docx", archive.getvalue())
        valid_office = io.BytesIO()
        with zipfile.ZipFile(valid_office, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("word/document.xml", "<document/>")
        self.assertEqual(
            policy.validate_upload("document.docx", valid_office.getvalue())["extension"],
            ".docx",
        )

    def test_upload_ingress_uses_shared_policy_and_public_scrubbing(self):
        experience = (ADDONS / "ai_experience/controllers/experience_api.py").read_text()
        semantic = (ADDONS / "ai_semantic_api/controllers/semantic_api.py").read_text()
        intelligence = (ADDONS / "ai_document_intelligence/models/intelligence.py").read_text()
        for source in (experience, semantic, intelligence):
            self.assertIn("validate_upload", source)
            self.assertIn("MAX_UPLOAD_BYTES", source)
        self.assertIn("scrub_public_text", experience)

    def test_release_manifest_matches_current_entries(self):
        manifest = json.loads((ROOT / "SHA256MANIFEST.json").read_text())
        self.assertEqual(len(manifest), 392)
        missing = [path for path in manifest if not (ROOT / path).is_file()]
        self.assertEqual(missing, [])
        mismatched = [
            path for path, digest in manifest.items()
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest
        ]
        self.assertEqual(mismatched, [])
        for path in (
            "00_final_production_install.sh", "01_setup_base.sh",
            "02_install_modules.sh", "03_start_all.sh",
            "custom_addons/ai_gateway/controllers/file_policy.py",
            "custom_addons/ai_gateway/migrations/18.0.1.1.0/pre-migrate.py",
        ):
            self.assertIn(path, manifest)

    def test_all_python_sources_compile(self):
        for path in ADDONS.rglob("*.py"):
            try:
                ast.parse(path.read_text(), filename=str(path))
            except SyntaxError as exc:  # pragma: no cover - assertion context
                self.fail(f"syntax error in {path}: {exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
