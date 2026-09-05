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
        self.assertIn("all_installed_modules_agent_connected", source)
        self.assertIn("if adapters is not None", source)
        self.assertIn("if subscriptions is not None", source)

    def test_customer_appliance_module_install_and_navigation_contract(self):
        controller = (ADDONS / "ai_control_plane/controllers/api.py").read_text()
        installer = (ADDONS / "ai_control_plane/models/module_install.py").read_text()
        admin = (ROOT / "frontend/src/pages/AdminPage.jsx").read_text()
        app = (ROOT / "frontend/src/App.jsx").read_text()
        workspace = (ROOT / "frontend/src/pages/ModuleWorkspacePage.jsx").read_text()
        docs = (ROOT / "CUSTOMER_APPLIANCE_MODULES.md").read_text()
        for marker in (
            "/api/admin/modules", "/api/admin/modules/install", "/api/admin/modules/<int:module_id>/readiness", "button_immediate_install",
            "dependencies_id", "automatic_pending", "request_key", "_is_privileged",
            "/api/modules/navigation", "/api/modules/menus/", "groups_id",
            "adminInstallModule", "_safe_action_fields", "read_only",
        ):
            self.assertIn(marker, controller + installer + admin + app + workspace)
        self.assertIn("one appliance", docs)
        self.assertIn("official business application", docs)
        self.assertIn("reviewed adapter", docs)
        self.assertNotIn("payload.get(\"model\")", controller)
        self.assertNotIn("payload.get(\"command\")", controller)

    def test_universal_onboarding_is_automatic_and_statused(self):
        discovery = (ADDONS / "ai_integration/models/discovery.py").read_text()
        module = (ADDONS / "ai_control_plane/models/integration.py").read_text()
        sync = (ADDONS / "ai_control_plane/models/module_sync.py").read_text()
        cron = (ADDONS / "ai_control_plane/data/cron_data.xml").read_text()
        for marker in (
            "_ensure_discovered_operation", "_ensure_event_mappings", "menu_names_json",
            "view_names_json", "scope_json", "certification_state", "discovered_read", "adapter-required",
            "unavailable_mutations_json",
        ):
            self.assertIn(marker, discovery + module)
        self.assertIn("postcommit.add", sync)
        self.assertIn('<field name="interval_type">minutes</field>', cron)

    def test_rag_memory_and_100_request_path_are_bounded(self):
        chunk = (ADDONS / "ai_rag/models/document_chunk.py").read_text()
        rag_tool = (ADDONS / "ai_rag/models/rag_tool.py").read_text()
        embedding = (ADDONS / "ai_rag/models/embedding_client.py").read_text()
        reader = (ADDONS / "company_ai_demo/models/file_reader.py").read_text()
        memory = (ADDONS / "company_ai_demo/models/memory_record.py").read_text()
        memory_tool = (ADDONS / "company_ai_demo/models/agent_memory.py").read_text()
        memory_rules = (ADDONS / "company_ai_demo/security/memory_rules.xml").read_text()
        queue = (ADDONS / "ai_gateway/models/chat_queue.py").read_text()
        benchmark = (ROOT / "60_v58_llm_benchmark.py").read_text()
        capacity = (ROOT / "61_v58_capacity_gate.py").read_text()
        for marker in (
            "candidate_limit", "RAG_MIN_VECTOR_SCORE", "hybrid_score", "retrieval_mode",
            "ai_document_chunk_embedding_hnsw_idx", "_query_cache_key", "No sufficiently relevant",
            "same certified embedding service", "limit=10 if not query else 500",
            "rule_memory_company_hr_manager", "Memory key must contain", "existing",
            "_POOL_MAX_WAITERS", "100-request burst", "default=100", "AI_MIN_CONCURRENCY",
        ):
            self.assertIn(marker, chunk + rag_tool + embedding + reader + memory + memory_tool + memory_rules + queue + benchmark + capacity)
        self.assertNotIn("SentenceTransformer", reader)
        self.assertNotIn('"provider": "odoo-orm-canonical"', memory_tool)

    def test_personal_workspace_uses_shared_agent_core(self):
        identity = (ADDONS / "ai_gateway/models/agent_identity.py").read_text()
        thread = (ADDONS / "ai_gateway/models/personal_thread.py").read_text()
        gateway = (ADDONS / "ai_gateway/controllers/gateway.py").read_text()
        experience = (ADDONS / "ai_experience/controllers/experience_api.py").read_text()
        frontend = (ROOT / "frontend/src/pages/ChatPage.jsx").read_text()
        app = (ROOT / "frontend/src/App.jsx").read_text()
        for marker in (
            "ensure_personal", "personal_workspace", "current_user_permissions",
            "personal_agent_identity_id", "shared_core", "personal_agent",
            "دستیار شخصی شما", '"id": "personal"', "getAgents", "هسته مشترک، پروفایل شخصی",
        ):
            self.assertIn(marker, identity + thread + gateway + experience + frontend + app)
        self.assertNotIn('"id": a.id', experience)

    def test_every_installed_module_is_connected_to_the_single_agent_catalog(self):
        binding = (ADDONS / "ai_integration/models/agent_module_binding.py").read_text()
        discovery = (ADDONS / "ai_integration/models/discovery.py").read_text()
        gateway = (ADDONS / "ai_gateway/controllers/gateway.py").read_text()
        gate = (ADDONS / "ai_gateway/models/execution_gate.py").read_text()
        tool_risk = (ADDONS / "ai_business_tools/models/tool_risk.py").read_text()
        control = (ADDONS / "ai_control_plane/models/integration.py").read_text()
        hooks = (ADDONS / "ai_integration/hooks.py").read_text()
        certification = (ADDONS / "ai_integration/models/certification.py").read_text()
        runtime = (ROOT / "51_v48_runtime_e2e.py").read_text()
        frontend = (ROOT / "frontend/src/pages/ModuleWorkspacePage.jsx").read_text()
        for marker in (
            "ai.integration.agent.module", "Company Assistant", "sync_installed_module_bindings",
            "post_init_hook", "tool_ids_for_agent", "connected_no_tools", "agent_connection_state",
            "assistant.sudo().write({\"tool_ids\"", "_agent_tools", "agent_tools",
            "owner_module_not_installed", "tool_owner_missing", "module_name = fields.Char",
        ):
            self.assertIn(marker, binding + discovery + gateway + gate + tool_risk + control + hooks)
        for marker in (
            "company_assistant_identity", "agent_tool_catalog_binding", "binding_counts_consistent",
            "single_company_assistant_binding", "binding.catalog.", "binding.counts.",
        ):
            self.assertIn(marker, certification + runtime)
        risk_rows = list(xml_records("ai.gateway.tool.risk"))
        self.assertTrue(risk_rows)
        self.assertTrue(all(values.get("module_name") for _, _, values in risk_rows))
        self.assertIn("agent_connection", frontend)
        self.assertIn("tool_count", frontend)

    def test_discovered_reads_and_mutations_have_separate_contracts(self):
        registry = (ADDONS / "ai_integration/models/unified_registry.py").read_text()
        certification = (ADDONS / "ai_integration/models/certification.py").read_text()
        discovery = (ADDONS / "ai_integration/models/discovery.py").read_text()
        event_outbox = (ADDONS / "ai_integration/models/module_event.py").read_text()
        self.assertIn("discovered_model_read", registry)
        self.assertIn("('source', '=', 'discovered')", registry)
        self.assertIn("('coverage', '=', 'discovered_read')", registry)
        self.assertIn("reviewed_operational", certification)
        self.assertIn("business_operations_registered", certification)
        self.assertIn("ai_integration_change_outbox", event_outbox)
        self.assertIn("jsonb_build_object", event_outbox)
        self.assertIn("_ensure_event_mappings", discovery)
        self.assertNotIn("Model.create(args", registry)
        self.assertNotIn("Model.write(args", registry)

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

    def test_authorization_uses_optional_models_when_they_are_installed(self):
        authorization = (ADDONS / "ai_control_plane/models/authorization.py").read_text()
        rag = (ADDONS / "ai_rag/models/document_chunk.py").read_text()
        self.assertIn("grant_model is not None", authorization)
        self.assertIn("assignment_model is not None", authorization)
        self.assertIn("grant_model is not None", rag)

    def test_admin_and_authorization_surfaces_are_current_company_scoped(self):
        semantic = (ADDONS / "ai_semantic_api/controllers/semantic_api.py").read_text()
        gateway = (ADDONS / "ai_gateway/controllers/gateway.py").read_text()
        grants = (ADDONS / "ai_business_tools/models/access_grant.py").read_text()
        grant_rule = (ADDONS / "ai_business_tools/security/access_grant_role_rules.xml").read_text()
        assignments = (ADDONS / "ai_customer_plane/models/role_assignment.py").read_text()
        self.assertIn("_scoped_user_env(user)", semantic)
        self.assertIn('("company_id", "=", env.company.id)', semantic)
        self.assertIn("allowed_company_ids=[user.company_id.id]", gateway)
        self.assertIn('("company_id", "=", self.env.company.id)', grants)
        self.assertIn("('company_id', 'in', company_ids)", grant_rule)
        self.assertIn("self.env.company.id", assignments)

    def test_rag_jobs_have_a_durable_lease_and_atomic_claim(self):
        source = (ADDONS / "ai_rag/models/index_job.py").read_text()
        self.assertIn("lease expired", source)
        self.assertIn("FOR UPDATE SKIP LOCKED", source)
        self.assertIn("attempts >= 3", source)

    def test_experience_model_presence_checks_do_not_treat_empty_recordsets_as_missing(self):
        experience = (ADDONS / "ai_experience/controllers/experience_api.py").read_text()
        self.assertNotIn("if not model:", experience)
        self.assertNotIn("if assistants:", experience)
        self.assertIn("if model is not None:", experience)

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
        self.assertGreaterEqual(len(manifest), 422)
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
            "custom_addons/ai_business_tools/migrations/18.0.1.6.0/pre-migrate.py",
            "custom_addons/ai_business_tools/migrations/18.0.1.6.0/post-migrate.py",
            "custom_addons/ai_integration/migrations/18.0.2.1.0/post-migrate.py",
            "custom_addons/ai_integration/models/reviewed_operation_tools.py",
            "custom_addons/ai_control_plane/models/module_install.py",
            "frontend/src/pages/ModuleWorkspacePage.jsx",
            "CUSTOMER_APPLIANCE_MODULES.md",
        ):
            self.assertIn(path, manifest)

    def test_approval_expiration_is_durable_and_audited(self):
        approval = (ADDONS / "ai_business_tools/models/approval.py").read_text()
        cron = (ADDONS / "ai_business_tools/data/cron_data.xml").read_text()
        history = (ADDONS / "ai_business_tools/models/approval_history.py").read_text()
        self.assertIn('("expired", "Expired")', approval)
        self.assertIn("def cron_expire_pending", approval)
        self.assertIn('"approval.expired"', approval)
        self.assertIn('event": "expired"', approval)
        self.assertIn('id="cron_expire_ai_approvals"', cron)
        self.assertIn('model.cron_expire_pending()', cron)
        self.assertIn('("expired", "Expired")', history)

    def test_reviewed_operation_dispatch_is_bounded(self):
        source = (ADDONS / "ai_integration/models/reviewed_operation_tools.py").read_text()
        registry = (ADDONS / "ai_integration/models/unified_registry.py").read_text()
        self.assertIn("arguments_json", source)
        self.assertIn("json.loads", source)
        self.assertIn("ai.integration.unified.registry", source)
        self.assertIn("module_read_summary", registry)
        self.assertIn("_MODULE_READ_MODELS", registry)
        self.assertNotIn("args.get('model')", registry)

    def test_approved_execution_uses_approver_identity(self):
        gate = (ADDONS / "ai_gateway/models/execution_gate.py").read_text()
        self.assertIn("approval.decided_by_id.id != self.env.user.id", gate)
        self.assertNotIn("approval.requested_by_id.id != self.env.user.id", gate)

    def test_model_promotion_is_benchmark_and_evidence_gated(self):
        registry = (ADDONS / "ai_integration/models/model_registry.py").read_text()
        benchmark = (ROOT / "60_v58_llm_benchmark.py").read_text()
        self.assertIn("action_promote_from_benchmark", registry)
        self.assertIn("system administrator", registry)
        self.assertIn("db_redis_metrics", registry)
        self.assertIn("min_concurrency", registry)
        self.assertIn('"vision"', benchmark)
        self.assertIn('"embedding"', benchmark)
        self.assertIn("image_url", benchmark)

    def test_workflow_deadline_recheck_and_hybrid_rag_contract(self):
        workflow = ET.parse(ADDONS / "ai_workflow/data/default_workflows.xml")
        record = workflow.find(".//record[@id='workflow_task_deadline_escalation']")
        definition = json.loads(record.findtext("field[@name='definition_json']"))
        self.assertEqual(definition["schema_version"], 1)
        self.assertEqual([step["action"] for step in definition["steps"]],
                         ["branch", "wait_until", "tool", "branch", "notify", "escalate", "noop"])
        self.assertEqual(definition["steps"][2]["tool"], "get_task_status")
        self.assertEqual(definition["steps"][3]["then"], 6)
        self.assertEqual(definition["steps"][3]["else"], 4)
        rag = (ADDONS / "ai_rag/models/document_chunk.py").read_text()
        self.assertIn("ts_rank_cd", rag)
        self.assertIn("retrieval_mode", rag)
        self.assertIn("allowed_doc_ids", rag)
        self.assertIn("status", rag)
        self.assertIn("active_snapshot", rag)
        rag_index = (ADDONS / "ai_rag/models/rag_index.py").read_text()
        self.assertIn("class AiRagIndexSnapshot", rag_index)
        self.assertIn("content_checksum", rag_index)
        benchmark = (ROOT / "60_v58_llm_benchmark.py").read_text()
        self.assertIn("ttft_ms", benchmark)
        self.assertIn("p95", benchmark)

    def test_customer_setup_center_phase_one_contract(self):
        branding = (ADDONS / "ai_customer_plane/models/branding.py").read_text()
        setup_run = (ADDONS / "ai_customer_plane/models/setup_run.py").read_text()
        rules = (ADDONS / "ai_customer_plane/security/customer_rules.xml").read_text()
        access = (ADDONS / "ai_customer_plane/security/ir.model.access.csv").read_text()
        manifest = (ADDONS / "ai_customer_plane/__manifest__.py").read_text()
        migration = (ADDONS / "ai_customer_plane/migrations/18.0.7.0.0/post-migrate.py").read_text()
        debrand_manifest = (ADDONS / "ai_debrand/__manifest__.py").read_text()
        debrand_templates = (ADDONS / "ai_debrand/views/debrand_templates.xml").read_text()
        semantic = (ADDONS / "ai_semantic_api/controllers/semantic_api.py").read_text()
        admin = (ROOT / "frontend/src/pages/AdminPage.jsx").read_text()
        app = (ROOT / "frontend/src/App.jsx").read_text()
        for marker in (
            '_name = "ai.customer.branding"',
            'unique(company_id)',
            "company_id = fields.Many2one",
            "attachment=True",
            "_COLOR_FIELDS",
            "_validate_hex",
            "_validate_asset",
            "public_values",
            "export_snapshot",
        ):
            self.assertIn(marker, branding)
        for marker in (
            '_name = "ai.customer.setup.run"',
            'unique(run_key)',
            'action_start',
            'action_advance',
            'action_pass',
            'action_fail',
            'action_cancel',
            'runtime_certification_state',
        ):
            self.assertIn(marker, setup_run)
        for marker in (
            'model_ai_customer_branding',
            'model_ai_customer_setup_run',
            'company_ids',
        ):
            self.assertIn(marker, rules + access)
        self.assertIn('"version": "18.0.8.0.0"', manifest)
        self.assertIn('ai.customer.branding', migration)
        self.assertIn('ai.brand.name', migration)
        self.assertIn('ai.brand.domain', migration)
        self.assertNotIn('custom_css', branding)
        self.assertIn('"ai_customer_plane"', debrand_manifest)
        self.assertIn('ai.customer.branding', debrand_templates)
        for marker in (
            '"/api/branding"', '"/api/branding/logo"', '"/api/branding/favicon"',
            '"/api/admin/setup"', '"/api/admin/setup/company"',
            '"/api/admin/branding"', '_decode_brand_asset',
            '_BRAND_COLOR_FIELDS', 'unsupported branding fields',
            '"/api/admin/configuration-profiles"', '/validate', '/compile',
            '/activate', '/dry-run', 'active profile must be cloned',
        ):
            self.assertIn(marker, semantic)
        for marker in (
            'adminGetSetup', 'adminUpdateCompany', 'راه‌اندازی مشتری',
            'logo_base64', 'favicon_base64', 'branding:changed',
            'show_module_navigation', 'adminListConfigurationProfiles',
            'Configuration Profiles', 'Deployment dry-run', 'adminGetModuleReadiness',
        ):
            self.assertIn(marker, admin + app)

    def test_configuration_profile_history_clone_and_setup_checklist_contract(self):
        semantic = (ADDONS / "ai_semantic_api/controllers/semantic_api.py").read_text()
        profile = (ADDONS / "ai_customer_plane/models/customer_config.py").read_text()
        history = (ADDONS / "ai_customer_plane/models/profile_history.py").read_text()
        migration = (ADDONS / "ai_customer_plane/migrations/18.0.8.0.0/post-migrate.py").read_text()
        manifest = (ADDONS / "ai_customer_plane/__manifest__.py").read_text()
        access = (ADDONS / "ai_customer_plane/security/ir.model.access.csv").read_text()
        rules = (ADDONS / "ai_customer_plane/security/customer_rules.xml").read_text()
        frontend_api = (ROOT / "frontend/src/api/client.js").read_text()
        admin = (ROOT / "frontend/src/pages/AdminPage.jsx").read_text()
        for marker in (
            '"/api/admin/configuration-profiles/<int:profile_id>/clone"',
            '"/api/admin/configuration-profiles/<int:profile_id>/history"',
            '"/api/admin/setup/checklist"',
            '"/api/admin/setup/checklist/run"',
            '"/api/admin/setup/runs"',
            '"/api/admin/setup/runs/<string:run_key>"',
            "_require_privileged()", '("company_id", "=", env.company.id)',
            "_audit(env, env.user.id", "ready_for_customer_handoff",
        ):
            self.assertIn(marker, semantic)
        for marker in ("create_snapshot", "def clone", "_record_history", "state changed", "compiled_hash"):
            self.assertIn(marker, profile + history)
        self.assertIn("Profile history snapshots are immutable", history)
        self.assertIn("Profile history snapshots cannot be deleted", history)
        self.assertIn("18.0.8.0.0", manifest + migration)
        self.assertIn("ai.customer.configuration.profile.history", migration)
        self.assertIn("model_ai_customer_configuration_profile_history", access + rules)
        for marker in (
            "adminCloneConfigurationProfile", "adminGetConfigurationProfileHistory",
            "adminGetSetupChecklist", "adminRunSetupChecklist", "adminListSetupRuns",
            "Clone به draft", "History:", "Deployment checklist", "اجرای checklist",
            "PROFILE_FIELD_SCHEMAS", "ProfileSectionEditor", "ویرایش پیشرفته JSON",
        ):
            self.assertIn(marker, frontend_api + admin)

    def test_all_python_sources_compile(self):
        for path in ADDONS.rglob("*.py"):
            try:
                ast.parse(path.read_text(), filename=str(path))
            except SyntaxError as exc:  # pragma: no cover - assertion context
                self.fail(f"syntax error in {path}: {exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
