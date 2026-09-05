import React, { useEffect, useState } from "react";
import {
  adminListRoles, adminListUsers, adminListAccessGrants, adminCreateAccessGrant,
  adminRevokeAccessGrant, adminListDocuments, adminListAgents, adminGetBranding,
  adminUpdateBranding, adminGetMetrics, adminListModules, adminInstallModule,
  adminGetSetup, adminUpdateCompany, adminListConfigurationProfiles,
  adminCreateConfigurationProfile, adminGetConfigurationProfile,
  adminCloneConfigurationProfile, adminGetConfigurationProfileHistory,
  adminUpdateConfigurationProfile, adminValidateConfigurationProfile,
  adminCompileConfigurationProfile, adminActivateConfigurationProfile,
  adminArchiveConfigurationProfile, adminDryRunConfigurationProfile,
  adminGetSetupChecklist, adminRunSetupChecklist, adminListSetupRuns,
  adminGetModuleReadiness, ApiError,
} from "../api/client.js";
import {
  Card, Table, Badge, Button, Tabs, Alert, Spinner, EmptyState, Modal, Select, Input, TextArea,
} from "../components";

// Admin Console (roadmap #46) — "a separate admin section (not the
// Odoo backend itself) that only shows product settings (Role,
// documents, agents, branding)". Every tab below is a thin read (and,
// for Access Grants/Branding, write) view over an /api/admin/* route
// that already existed as data (res.groups, ai.gateway.access.grant,
// ai.gateway.tool.risk, res.company) - see semantic_api.py for what
// each endpoint actually does and why it's safe to expose here.
//
// This whole page assumes the caller already passed the /api/me
// is_admin check in App.jsx before rendering it - but every API call
// it makes is independently re-checked server-side regardless
// (_require_privileged()), so a stale/forged client-side flag can't
// actually see anything a real privilege check would refuse.

const TABS = [
  { key: "setup", label: "راه‌اندازی مشتری" },
  { key: "profiles", label: "Configuration Profiles" },
  { key: "roles", label: "نقش‌ها" },
  { key: "grants", label: "دسترسی موقت / تفویض" },
  { key: "documents", label: "اسناد" },
  { key: "agents", label: "ایجنت‌ها" },
  { key: "branding", label: "برندینگ" },
  { key: "observability", label: "مانیتورینگ" },
  { key: "modules", label: "برنامه‌ها" },
  { key: "control", label: "Control Plane" },
];

function useLoad(loader, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  function refresh() {
    setError("");
    loader()
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "خطا در بارگذاری"));
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, deps);
  return [data, error, refresh];
}

export default function AdminPage() {
  const [tab, setTab] = useState("roles");
  return (
    <div>
      <h2>کنسول مدیریت</h2>
      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      {tab === "setup" && <SetupTab />}
      {tab === "profiles" && <ProfilesTab />}
      {tab === "roles" && <RolesTab />}
      {tab === "grants" && <GrantsTab />}
      {tab === "documents" && <DocumentsTab />}
      {tab === "agents" && <AgentsTab />}
      {tab === "branding" && <BrandingTab />}
      {tab === "observability" && <ObservabilityTab />}
      {tab === "modules" && <ModulesTab />}
      {tab === "control" && <ControlPlaneTab />}
    </div>
  );
}

// --- Configuration Profiles -----------------------------------------------
const PROFILE_SECTIONS = [
  ["role_policy", "Role Policy"],
  ["capability_policy", "Capability Policy"],
  ["approval_matrix", "Approval Matrix"],
  ["document_policy", "Document Policy"],
  ["agent_config", "Agent Configuration"],
  ["tool_config", "Tool Configuration"],
  ["workflow_config", "Workflow Configuration"],
];

const EMPTY_PROFILE_SECTIONS = Object.fromEntries(PROFILE_SECTIONS.map(([key]) => [key, {}]));

const PROFILE_FIELD_SCHEMAS = {
  role_policy: [
    ["department", "Department", "text"], ["position", "Position", "text"],
    ["job_level", "Job level", "text"], ["location", "Location", "text"],
    ["employment_type", "Employment type", "text"], ["manager_required", "مدیر باید باشد", "boolean"],
  ],
  capability_policy: [
    ["allowed_capabilities", "قابلیت‌های مجاز (comma-separated)", "list"],
    ["denied_capabilities", "قابلیت‌های مسدود (comma-separated)", "list"],
  ],
  approval_matrix: [
    ["risk_threshold", "حد ریسک نیازمند تایید", "number"],
    ["approver_group", "گروه تاییدکننده", "text"],
    ["high_risk_requires_approval", "ریسک بالا نیازمند تایید است", "boolean"],
  ],
  document_policy: [
    ["default_access_level", "سطح دسترسی پیش‌فرض", "text"],
    ["ingestion_mode", "حالت ingestion", "text"],
    ["citation_required", "Citation اجباری است", "boolean"],
    ["retry_limit", "حد retry", "number"],
  ],
  agent_config: [
    ["agent_name", "نام Agent", "text"], ["provider", "Provider label", "text"],
    ["model", "Model label", "text"], ["risk_level", "سطح ریسک پیش‌فرض", "number"],
  ],
  tool_config: [
    ["allowed_tools", "ابزارهای مجاز (comma-separated)", "list"],
    ["denied_tools", "ابزارهای مسدود (comma-separated)", "list"],
    ["approval_required", "تایید برای ابزار لازم است", "boolean"],
  ],
  workflow_config: [
    ["default_workflow", "Workflow پیش‌فرض", "text"],
    ["notification_channel", "کانال اعلان", "text"],
    ["retry_limit", "حد retry", "number"],
  ],
};

function profileSectionObject(value) {
  if (value && typeof value === "object") return value;
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    return {};
  }
}

function ProfileSectionEditor({ sectionKey, label, value, disabled, onChange }) {
  const section = profileSectionObject(value);
  const schema = PROFILE_FIELD_SCHEMAS[sectionKey] || [];
  function update(field, raw, kind) {
    const next = { ...section };
    if (kind === "list") next[field] = String(raw).split(",").map((item) => item.trim()).filter(Boolean);
    else if (kind === "boolean") next[field] = Boolean(raw);
    else if (kind === "number") next[field] = raw === "" ? undefined : Number(raw);
    else next[field] = raw;
    if (next[field] === undefined) delete next[field];
    onChange(next);
  }
  return <div className="profile-section-editor">
    <h4>{label}</h4>
    {schema.length > 0 && <div className="admin-form-grid">
      {schema.map(([field, fieldLabel, kind]) => kind === "boolean"
        ? <label className="admin-toggle" key={field}><input type="checkbox" checked={Boolean(section[field])} disabled={disabled} onChange={(e) => update(field, e.target.checked, kind)} /><span>{fieldLabel}</span></label>
        : <Input key={field} label={fieldLabel} type={kind === "number" ? "number" : "text"} value={kind === "list" ? (Array.isArray(section[field]) ? section[field].join(", ") : "") : (section[field] ?? "")} disabled={disabled} onChange={(e) => update(field, e.target.value, kind)} />)}
    </div>}
    <details className="profile-advanced-editor">
      <summary>ویرایش پیشرفته JSON برای فیلدهای تخصصی</summary>
      <TextArea label={`${label} — JSON object`} rows={4} value={typeof value === "string" ? value : JSON.stringify(section, null, 2)} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
    </details>
  </div>;
}

function ProfilesTab() {
  const [data, error, refresh] = useLoad(adminListConfigurationProfiles, []);
  const [selectedId, setSelectedId] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [history, setHistory] = useState(null);
  const [historyError, setHistoryError] = useState("");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (data?.profiles?.length && !selectedId) setSelectedId(data.profiles[0].id);
  }, [data, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    setProfile(null);
    setHistory(null);
    setLoadError("");
    setHistoryError("");
    adminGetConfigurationProfile(selectedId)
      .then((value) => setProfile(value.profile))
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : "خطا در بارگذاری profile"));
    adminGetConfigurationProfileHistory(selectedId)
      .then((value) => setHistory(value.history))
      .catch((err) => setHistoryError(err instanceof ApiError ? err.message : "خطا در بارگذاری history"));
  }, [selectedId]);

  function refreshHistory() {
    if (!selectedId) return;
    adminGetConfigurationProfileHistory(selectedId)
      .then((value) => { setHistory(value.history); setHistoryError(""); })
      .catch((err) => setHistoryError(err instanceof ApiError ? err.message : "خطا در بارگذاری history"));
  }

  async function createProfile() {
    const name = window.prompt("نام profile را وارد کنید", "پروفایل اولیه مشتری");
    if (!name?.trim()) return;
    setBusy("create");
    setResult(null);
    try {
      const value = await adminCreateConfigurationProfile({ name: name.trim(), ...EMPTY_PROFILE_SECTIONS });
      setSelectedId(value.profile.id);
      refresh();
    } catch (err) {
      setResult({ error: err instanceof ApiError ? err.message : "ساخت profile ناموفق بود" });
    } finally {
      setBusy("");
    }
  }

  function updateSection(key, raw) {
    setProfile((current) => ({ ...current, sections: { ...current.sections, [key]: raw } }));
  }

  async function saveProfile() {
    if (!profile || profile.state === "active") return;
    const payload = { name: profile.name };
    try {
      PROFILE_SECTIONS.forEach(([key]) => {
        const section = profile.sections[key];
        payload[key] = typeof section === "string" ? JSON.parse(section || "{}") : (section || {});
      });
    } catch (err) {
      setResult({ error: `JSON بخش ${err.message || "نامعتبر"}` });
      return;
    }
    setBusy("save");
    setResult(null);
    try {
      const value = await adminUpdateConfigurationProfile(profile.id, payload);
      setProfile(value.profile);
      refresh();
      refreshHistory();
    } catch (err) {
      setResult({ error: err instanceof ApiError ? err.message : "ذخیره profile ناموفق بود" });
    } finally {
      setBusy("");
    }
  }

  async function cloneProfile() {
    if (!profile) return;
    const name = window.prompt("نام profile جدید را وارد کنید", `${profile.name} — draft`);
    if (!name?.trim()) return;
    setBusy("clone");
    setResult(null);
    try {
      const value = await adminCloneConfigurationProfile(profile.id, name.trim());
      setSelectedId(value.profile.id);
      setResult({ status: "cloned", source_profile_id: profile.id, profile: value.profile });
      refresh();
    } catch (err) {
      setResult({ error: err instanceof ApiError ? err.message : "clone profile ناموفق بود" });
    } finally {
      setBusy("");
    }
  }

  async function action(name, handler) {
    if (!profile) return;
    setBusy(name);
    setResult(null);
    try {
      const value = await handler(profile.id);
      setResult(value);
      if (value.profile) setProfile(value.profile);
      refresh();
      refreshHistory();
    } catch (err) {
      setResult({ error: err instanceof ApiError ? err.message : "عملیات profile ناموفق بود" });
    } finally {
      setBusy("");
    }
  }

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <>
      <Card title="Configuration Profiles" actions={<Button size="sm" onClick={createProfile} loading={busy === "create"}>+ profile جدید</Button>}>
        <p className="muted">هر profile نسخه‌ای از role، capability، approval، document، agent، tool و workflow policy مشتری است. profile فعال مستقیماً ویرایش نمی‌شود.</p>
        {!data.profiles.length && <EmptyState text="Configuration profileای وجود ندارد." />}
        {data.profiles.length > 0 && <Table columns={[
          { key: "name", header: "نام", render: (row) => <button className="profile-list-button" onClick={() => setSelectedId(row.id)}>{row.name}</button> },
          { key: "state", header: "وضعیت", render: (row) => <Badge tone={row.state === "active" ? "success" : row.state === "archived" ? "neutral" : "warning"}>{row.state}</Badge> },
          { key: "version", header: "نسخه" },
          { key: "compiled_hash", header: "Compile", render: (row) => row.compiled_hash ? <Badge tone="success">compiled</Badge> : <Badge tone="warning">نیازمند compile</Badge> },
        ]} rows={data.profiles} />}
      </Card>
      {loadError && <Alert>{loadError}</Alert>}
      {profile && (
        <Card title={`ویرایش profile: ${profile.name}`}>
          <div className="profile-toolbar">
            <Badge tone={profile.state === "active" ? "success" : profile.state === "archived" ? "neutral" : "warning"}>{profile.state}</Badge>
            <span className="muted">نسخه {profile.version} · hash: {profile.compiled_hash || "ندارد"}</span>
            <Button size="sm" variant="ghost" onClick={cloneProfile} loading={busy === "clone"}>Clone به draft</Button>
            <Button size="sm" variant="ghost" onClick={refreshHistory}>تازه‌سازی history</Button>
          </div>
          <Input label="نام profile" value={profile.name} disabled={profile.state === "active"} onChange={(e) => setProfile({ ...profile, name: e.target.value })} />
          {PROFILE_SECTIONS.map(([key, label]) => <ProfileSectionEditor key={key} sectionKey={key} label={label} value={profile.sections[key]} disabled={profile.state === "active"} onChange={(value) => updateSection(key, value)} />)}
          <div className="profile-actions">
            <Button onClick={saveProfile} loading={busy === "save"} disabled={profile.state === "active"}>ذخیره draft</Button>
            <Button variant="ghost" onClick={() => action("validate", adminValidateConfigurationProfile)} loading={busy === "validate"}>اعتبارسنجی</Button>
            <Button variant="ghost" onClick={() => action("compile", adminCompileConfigurationProfile)} loading={busy === "compile"}>Compile</Button>
            <Button onClick={() => action("activate", adminActivateConfigurationProfile)} loading={busy === "activate"} disabled={profile.state === "active"}>فعال‌سازی</Button>
            <Button variant="ghost" onClick={() => action("dry-run", adminDryRunConfigurationProfile)} loading={busy === "dry-run"}>Deployment dry-run</Button>
            <Button variant="danger" onClick={() => action("archive", adminArchiveConfigurationProfile)} loading={busy === "archive"} disabled={profile.state === "active"}>Archive</Button>
          </div>
          {result && <pre className="profile-result">{JSON.stringify(result, null, 2)}</pre>}
        </Card>
      )}
      {profile && <Card title={`History: ${profile.name}`}>
        {historyError && <Alert>{historyError}</Alert>}
        {!history && !historyError && <Spinner />}
        {history && !history.length && <EmptyState text="برای این profile هنوز snapshot ثبت نشده است." />}
        {history && history.length > 0 && <Table columns={[
          { key: "version", header: "نسخه" },
          { key: "state", header: "وضعیت", render: (row) => <Badge tone={row.state === "active" ? "success" : row.state === "archived" ? "neutral" : "warning"}>{row.state}</Badge> },
          { key: "changed_by", header: "تغییردهنده" },
          { key: "changed_at", header: "زمان", render: (row) => row.changed_at || "—" },
          { key: "compiled_hash", header: "Compile", render: (row) => row.compiled_hash ? <Badge tone="success">compiled</Badge> : <Badge tone="neutral">—</Badge> },
          { key: "snapshot", header: "Snapshot", render: (row) => <details><summary>مشاهده</summary><pre className="profile-result">{JSON.stringify(row.snapshot, null, 2)}</pre></details> },
        ]} rows={history} />}
      </Card>}
    </>
  );
}

// --- Roles (#4/#5/#6) ----------------------------------------------------
function RolesTab() {
  const [data, error] = useLoad(adminListRoles, []);
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  if (data.roles.length === 0) return <EmptyState text="نقشی تعریف نشده." />;
  return (
    <Card title="نقش‌ها و اعضا">
      <Table
        columns={[
          { key: "name", header: "نقش" },
          { key: "comment", header: "توضیح" },
          {
            key: "implied_roles", header: "گروه‌های زیربنایی",
            render: (r) => r.implied_roles.join("، ") || "—",
          },
          { key: "member_count", header: "تعداد اعضا" },
          {
            key: "members", header: "اعضا",
            render: (r) => r.members.map((m) => m.name).join("، ") || "—",
          },
        ]}
        rows={data.roles}
      />
    </Card>
  );
}

// --- Access Grants (#41/#42) ---------------------------------------------
function GrantsTab() {
  const [data, error, refresh] = useLoad(adminListAccessGrants, []);
  const [users, setUsers] = useState(null);
  const [roles, setRoles] = useState(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ to_user_id: "", group_id: "", expires_on: "", reason: "" });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  function openModal() {
    setFormError("");
    setOpen(true);
    if (!users) adminListUsers().then((d) => setUsers(d.users)).catch((err) => setFormError(err instanceof ApiError ? err.message : "خطا در بارگذاری کاربران"));
    if (!roles) adminListRoles().then((d) => setRoles(d.roles)).catch((err) => setFormError(err instanceof ApiError ? err.message : "خطا در بارگذاری نقش‌ها"));
  }

  async function handleCreate(e) {
    e.preventDefault();
    setSaving(true);
    setFormError("");
    try {
      await adminCreateAccessGrant({
        to_user_id: Number(form.to_user_id),
        group_id: Number(form.group_id),
        expires_on: form.expires_on,
        reason: form.reason,
      });
      setOpen(false);
      setForm({ to_user_id: "", group_id: "", expires_on: "", reason: "" });
      refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "ثبت ناموفق بود");
    } finally {
      setSaving(false);
    }
  }

  async function handleRevoke(grantId) {
    try {
      await adminRevokeAccessGrant(grantId);
      refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "لغو ناموفق بود");
    }
  }

  const STATE_TONE = { scheduled: "info", active: "success", expired: "neutral", revoked: "danger" };
  const STATE_LABEL = { scheduled: "زمان‌بندی‌شده", active: "فعال", expired: "منقضی‌شده", revoked: "لغوشده" };

  return (
    <Card
      title="دسترسی‌های موقت و تفویض‌شده"
      actions={<Button size="sm" onClick={openModal}>+ دسترسی جدید</Button>}
    >
      <Alert>{error || formError}</Alert>
      {!data && <Spinner />}
      {data && data.grants.length === 0 && <EmptyState text="دسترسی موقتی ثبت نشده." />}
      {data && data.grants.length > 0 && (
        <Table
          columns={[
            { key: "to_user", header: "کاربر" },
            { key: "role", header: "نقش" },
            { key: "delegated_from", header: "تفویض‌شده از", render: (g) => g.delegated_from || "—" },
            { key: "expires_on", header: "انقضا" },
            { key: "state", header: "وضعیت", render: (g) => <Badge tone={STATE_TONE[g.state]}>{STATE_LABEL[g.state] || g.state}</Badge> },
            {
              key: "actions", header: "",
              render: (g) => (g.state === "scheduled" || g.state === "active") && (
                <Button size="sm" variant="danger" onClick={() => handleRevoke(g.id)}>لغو</Button>
              ),
            },
          ]}
          rows={data.grants}
        />
      )}

      <Modal
        open={open}
        title="دسترسی موقت جدید"
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>انصراف</Button>
            <Button onClick={handleCreate} loading={saving}
                    disabled={!form.to_user_id || !form.group_id || !form.expires_on}>
              ثبت
            </Button>
          </>
        }
      >
        <form onSubmit={handleCreate}>
          <Select
            label="کاربر" value={form.to_user_id} placeholder="انتخاب کنید..."
            onChange={(e) => setForm({ ...form, to_user_id: e.target.value })}
            options={(users || []).map((u) => ({ value: u.id, label: `${u.name} (${u.login})` }))}
          />
          <Select
            label="نقش" value={form.group_id} placeholder="انتخاب کنید..."
            onChange={(e) => setForm({ ...form, group_id: e.target.value })}
            options={(roles || []).map((r) => ({ value: r.id, label: r.name }))}
          />
          <Input
            label="تاریخ انقضا" type="date" required value={form.expires_on}
            onChange={(e) => setForm({ ...form, expires_on: e.target.value })}
          />
          <Input
            label="دلیل (اختیاری)" value={form.reason}
            onChange={(e) => setForm({ ...form, reason: e.target.value })}
          />
        </form>
      </Modal>
    </Card>
  );
}

// --- Documents overview (#26/#27, org-wide) -------------------------------
function DocumentsTab() {
  const [data, error] = useLoad(adminListDocuments, []);
  const ACCESS_LABEL = { company: "کل سازمان", department: "دپارتمان", group: "گروه", personal: "شخصی" };
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  if (data.documents.length === 0) return <EmptyState text="سندی ثبت نشده." />;
  return (
    <Card title={`همه‌ی اسناد سازمان (${data.documents.length})`}>
      <Table
        columns={[
          { key: "name", header: "نام" },
          { key: "access_level", header: "سطح دسترسی", render: (d) => <Badge>{ACCESS_LABEL[d.access_level]}</Badge> },
          { key: "department", header: "دپارتمان", render: (d) => d.department || "—" },
          { key: "group", header: "گروه", render: (d) => d.group || "—" },
          { key: "owner", header: "مالک", render: (d) => d.owner || "—" },
          { key: "create_date", header: "تاریخ ثبت", render: (d) => (d.create_date || "").slice(0, 10) },
        ]}
        rows={data.documents}
      />
    </Card>
  );
}

// --- Agents / Tool Registry (#15/#17/#20) ---------------------------------
function AgentsTab() {
  const [data, error] = useLoad(adminListAgents, []);
  const RISK_TONE = (level) => (level >= 4 ? "danger" : level >= 2 ? "warning" : "neutral");
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <>
      <Card title="دستیارها">
        {data.assistants.length === 0 && <EmptyState text="دستیاری تعریف نشده." />}
        {data.assistants.length > 0 && (
          <Table
            columns={[
              { key: "name", header: "نام" },
              { key: "tool_count", header: "تعداد قابلیت" },
              { key: "active", header: "فعال", render: (a) => <Badge tone={a.active ? "success" : "neutral"}>{a.active ? "بله" : "خیر"}</Badge> },
            ]}
            rows={data.assistants}
          />
        )}
        {data.vision_configured && <p className="muted">تحلیل تصویر برای این سازمان پیکربندی شده است.</p>}
      </Card>
      <Card title="رجیستری ابزارها و سطح ریسک">
        <Table
          columns={[
            { key: "name", header: "ابزار" },
            { key: "risk_level", header: "ریسک", render: (t) => <Badge tone={RISK_TONE(t.risk_level)}>RISK {t.risk_level}</Badge> },
            { key: "requires_approval_from", header: "نیازمند تایید", render: (t) => t.requires_approval_from || "—" },
            { key: "description", header: "توضیح" },
          ]}
          rows={data.tools}
        />
      </Card>
    </>
  );
}

// --- Customer Setup --------------------------------------------------------
function SetupTab() {
  const [data, error, refresh] = useLoad(adminGetSetup, []);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data && !form) setForm(data.company);
  }, [data, form]);

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setSaveError("");
    setSaved(false);
    try {
      await adminUpdateCompany(form);
      setSaved(true);
      setForm(null);
      refresh();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "ذخیره مشخصات شرکت ناموفق بود");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <Alert>{error}</Alert>;
  if (!data || !form) return <Spinner />;
  return (
    <>
      <Card title="راه‌اندازی مشتری">
        <p className="muted">این اطلاعات هویت appliance فعلی است و قبل از تحویل مشتری باید تکمیل شود.</p>
        <form onSubmit={handleSave}>
          <Input label="نام سازمان" required value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div className="admin-form-grid">
            <Input label="ایمیل سازمان" type="email" value={form.email || ""} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <Input label="تلفن" value={form.phone || ""} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            <Input label="وب‌سایت" type="url" value={form.website || ""} onChange={(e) => setForm({ ...form, website: e.target.value })} />
            <Input label="کشور" value={form.country_name || "—"} disabled />
            <Input label="واحد پول" value={form.currency_name || "—"} disabled />
          </div>
          <Input label="آدرس" value={form.street || ""} onChange={(e) => setForm({ ...form, street: e.target.value })} />
          <div className="admin-form-grid">
            <Input label="آدرس تکمیلی" value={form.street2 || ""} onChange={(e) => setForm({ ...form, street2: e.target.value })} />
            <Input label="شهر" value={form.city || ""} onChange={(e) => setForm({ ...form, city: e.target.value })} />
            <Input label="کد پستی" value={form.zip || ""} onChange={(e) => setForm({ ...form, zip: e.target.value })} />
          </div>
          {saved && <Alert tone="success">مشخصات سازمان ذخیره شد.</Alert>}
          <Alert>{saveError}</Alert>
          <Button type="submit" loading={saving}>ذخیره مشخصات سازمان</Button>
        </form>
      </Card>
      <Card title="وضعیت اولیه راه‌اندازی">
        <div className="setup-check-grid">
          <SetupCheck label="نام سازمان" ok={Boolean(form.name)} />
          <SetupCheck label="Brand name" ok={Boolean(data.branding?.brand_name)} />
          <SetupCheck label="Logo" ok={Boolean(data.branding?.has_logo)} />
          <SetupCheck label="Favicon" ok={Boolean(data.branding?.has_favicon)} />
          <SetupCheck label="Theme colors" ok={Boolean(data.branding?.primary_color)} />
        </div>
        <p className="muted">برای تنظیم لوگو، رنگ‌ها و ظاهر کامل، تب «برندینگ» را باز کنید.</p>
      </Card>
      <SetupChecklistPanel />
    </>
  );
}

function SetupCheck({ label, ok }) {
  return <div className="setup-check"><Badge tone={ok ? "success" : "warning"}>{ok ? "PASS" : "TODO"}</Badge><span>{label}</span></div>;
}

function SetupChecklistPanel() {
  const [checklist, checklistError, refreshChecklist] = useLoad(adminGetSetupChecklist, []);
  const [runs, runsError, refreshRuns] = useLoad(adminListSetupRuns, []);
  const [latestRun, setLatestRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const [runError, setRunError] = useState("");

  async function runChecklist() {
    setBusy(true);
    setRunError("");
    try {
      const result = await adminRunSetupChecklist();
      setLatestRun(result.run);
      refreshChecklist();
      refreshRuns();
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : "اجرای checklist ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  const checks = checklist?.checks || [];
  const summary = checklist?.summary || {};
  const stateTone = { pass: "success", fail: "danger", required: "warning" };
  const runTone = { passed: "success", failed: "danger", running: "info", queued: "warning" };
  return (
    <Card
      title="Deployment checklist و شواهد تحویل"
      actions={<Button size="sm" onClick={runChecklist} loading={busy}>اجرای checklist و ثبت run</Button>}
    >
      <p className="muted">این بررسی server-side و company-scoped است؛ نتیجه در یک setup run durable ذخیره می‌شود و با refresh صفحه از بین نمی‌رود.</p>
      <Alert>{checklistError || runsError || runError}</Alert>
      {checklist && <>
        <div className="setup-check-grid">
          <SetupCheck label="آماده تحویل مشتری" ok={Boolean(summary.ready_for_customer_handoff)} />
          <SetupCheck label={`موارد blocking: ${summary.blocking_passed || 0}/${summary.blocking_total || 0}`} ok={summary.blocking_total > 0 && summary.blocking_passed === summary.blocking_total} />
          <SetupCheck label={`هشدارها: ${summary.warning_total || 0}`} ok={summary.warning_total === 0} />
        </div>
        {checks.length > 0 && <Table columns={[
          { key: "label", header: "بررسی" },
          { key: "state", header: "نتیجه", render: (row) => <Badge tone={stateTone[row.state] || "neutral"}>{row.state.toUpperCase()}</Badge> },
          { key: "severity", header: "اثر", render: (row) => row.severity === "blocking" ? <Badge tone="danger">BLOCKING</Badge> : <Badge tone="warning">WARNING</Badge> },
          { key: "message", header: "شرح" },
          { key: "remediation", header: "اقدام اصلاحی", render: (row) => row.remediation || "—" },
        ]} rows={checks} />}
      </>}
      {latestRun && <div className="profile-result"><strong>آخرین اجرای همین نشست:</strong> {latestRun.run_key} · <Badge tone={runTone[latestRun.state] || "neutral"}>{latestRun.state}</Badge><pre>{JSON.stringify(latestRun.result, null, 2)}</pre></div>}
      {runs && runs.runs?.length > 0 && <>
        <h4>اجرای ثبت‌شده</h4>
        <Table columns={[
          { key: "run_key", header: "Run key" },
          { key: "state", header: "وضعیت", render: (row) => <Badge tone={runTone[row.state] || "neutral"}>{row.state}</Badge> },
          { key: "current_stage", header: "مرحله" },
          { key: "requested_by", header: "درخواست‌دهنده" },
          { key: "started_at", header: "شروع" },
          { key: "error_summary", header: "خطا", render: (row) => row.error_summary || "—" },
        ]} rows={runs.runs} />
      </>}
    </Card>
  );
}

// --- Branding (#55) --------------------------------------------------------
function BrandingTab() {
  const [data, error, refresh] = useLoad(adminGetBranding, []);
  const [form, setForm] = useState(null);
  const [logo, setLogo] = useState(null);
  const [favicon, setFavicon] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data && !form) {
      setForm({
        brand_name: data.brand_name || "",
        legal_name: data.legal_name || "",
        tagline: data.tagline || "",
        product_title: data.product_title || "",
        brand_domain: data.brand_domain || "",
        support_email: data.support_email || "",
        support_url: data.support_url || "",
        footer_text: data.footer_text || "",
        login_message: data.login_message || "",
        primary_color: data.primary_color,
        secondary_color: data.secondary_color,
        accent_color: data.accent_color,
        background_color: data.background_color,
        surface_color: data.surface_color,
        surface_alt_color: data.surface_alt_color,
        text_color: data.text_color,
        text_muted_color: data.text_muted_color,
        danger_color: data.danger_color,
        warning_color: data.warning_color,
        font_family: data.font_family || "system",
        border_radius: data.border_radius || "comfortable",
        show_ai_brand: data.show_ai_brand,
        show_powered_by: data.show_powered_by,
        show_module_navigation: data.show_module_navigation,
        support_contact_visible: data.support_contact_visible,
      });
    }
  }, [data, form]);

  function readFile(file, setter) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setter({ name: file.name, data: String(reader.result).split(",")[1] || "" });
    reader.onerror = () => setSaveError("خواندن فایل ناموفق بود");
    reader.readAsDataURL(file);
  }

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setSaveError("");
    setSaved(false);
    try {
      const payload = { ...form };
      if (logo) { payload.logo_base64 = logo.data; payload.logo_filename = logo.name; }
      if (favicon) { payload.favicon_base64 = favicon.data; payload.favicon_filename = favicon.name; }
      const result = await adminUpdateBranding(payload);
      setSaved(true);
      setLogo(null);
      setFavicon(null);
      setForm(null);
      refresh();
      window.dispatchEvent(new CustomEvent("branding:changed", { detail: result.branding }));
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "ذخیره برند ناموفق بود");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <Alert>{error}</Alert>;
  if (!data || !form) return <Spinner />;
  const colors = [
    ["primary_color", "رنگ اصلی"], ["secondary_color", "رنگ ثانویه"], ["accent_color", "رنگ موفقیت"],
    ["background_color", "پس‌زمینه"], ["surface_color", "سطح کارت"], ["surface_alt_color", "سطح دوم"],
    ["text_color", "متن"], ["text_muted_color", "متن کم‌رنگ"], ["danger_color", "خطا"], ["warning_color", "هشدار"],
  ];
  return (
    <Card title="تنظیمات کامل برند و White-label">
      <p className="muted">شرکت فعلی: {data.company_name} — نسخه برند: {data.version} — آخرین تغییر: {data.updated_at || "—"}</p>
      <form onSubmit={handleSave}>
        <h4>هویت و متن‌های مشتری</h4>
        <div className="admin-form-grid">
          <Input label="نام برند" required value={form.brand_name} onChange={(e) => setForm({ ...form, brand_name: e.target.value })} />
          <Input label="نام حقوقی" value={form.legal_name} onChange={(e) => setForm({ ...form, legal_name: e.target.value })} />
          <Input label="عنوان مرورگر" value={form.product_title} onChange={(e) => setForm({ ...form, product_title: e.target.value })} />
          <Input label="Tagline" value={form.tagline} onChange={(e) => setForm({ ...form, tagline: e.target.value })} />
          <Input label="دامنه برند" type="url" value={form.brand_domain} onChange={(e) => setForm({ ...form, brand_domain: e.target.value })} />
          <Input label="ایمیل پشتیبانی" type="email" value={form.support_email} onChange={(e) => setForm({ ...form, support_email: e.target.value })} />
          <Input label="لینک پشتیبانی" type="url" value={form.support_url} onChange={(e) => setForm({ ...form, support_url: e.target.value })} />
          <Input label="Footer" value={form.footer_text} onChange={(e) => setForm({ ...form, footer_text: e.target.value })} />
        </div>
        <Input label="پیام صفحه ورود" value={form.login_message} onChange={(e) => setForm({ ...form, login_message: e.target.value })} />
        <h4>دارایی‌های بصری</h4>
        <div className="admin-form-grid">
          <Input label={`لوگو ${data.has_logo ? "(ثبت شده)" : ""}`} type="file" accept=".png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff" onChange={(e) => readFile(e.target.files?.[0], setLogo)} />
          <Input label={`Favicon ${data.has_favicon ? "(ثبت شده)" : ""}`} type="file" accept="image/png,image/jpeg,image/webp,image/x-icon" onChange={(e) => readFile(e.target.files?.[0], setFavicon)} />
        </div>
        <p className="muted">فایل جدید جایگزین فایل قبلی می‌شود. حذف asset از مرحله بعدی reset امن انجام می‌شود.</p>
        <h4>رنگ و ظاهر</h4>
        <div className="admin-color-grid">
          {colors.map(([key, label]) => <label className="admin-color-field" key={key}><span>{label}</span><input type="color" value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} /><Input value={form[key]} aria-label={label} onChange={(e) => setForm({ ...form, [key]: e.target.value })} /></label>)}
        </div>
        <div className="admin-form-grid">
          <Select label="فونت" value={form.font_family} onChange={(e) => setForm({ ...form, font_family: e.target.value })} options={[{ value: "system", label: "System" }, { value: "vazirmatn", label: "Vazirmatn" }, { value: "inter", label: "Inter" }]} />
          <Select label="گردی کارت‌ها" value={form.border_radius} onChange={(e) => setForm({ ...form, border_radius: e.target.value })} options={[{ value: "compact", label: "Compact" }, { value: "comfortable", label: "Comfortable" }, { value: "rounded", label: "Rounded" }]} />
        </div>
        <h4>تجربه کاربری</h4>
        {[["show_ai_brand", "نمایش برند AI"], ["show_powered_by", "نمایش Powered by"], ["show_module_navigation", "نمایش منوی ماژول‌ها"], ["support_contact_visible", "نمایش اطلاعات پشتیبانی"]].map(([key, label]) => <label key={key} className="admin-toggle"><input type="checkbox" checked={Boolean(form[key])} onChange={(e) => setForm({ ...form, [key]: e.target.checked })} /><span>{label}</span></label>)}
        {saved && <Alert tone="success">برند با موفقیت ذخیره و برای frontend اعمال شد.</Alert>}
        <Alert>{saveError}</Alert>
        <Button type="submit" loading={saving}>ذخیره و اعمال برند</Button>
      </form>
    </Card>
  );
}

// --- Observability (#48) --------------------------------------------------
function ObservabilityTab() {
  const [data, error, refresh] = useLoad(adminGetMetrics, []);
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <Card title="مانیتورینگ (خلاصه‌ی همان /api/metrics)" actions={<Button size="sm" variant="ghost" onClick={refresh}>تازه‌سازی</Button>}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 }}>
        <Metric label="درخواست‌های ساعت اخیر" value={data.requests_last_hour} />
        <Metric label="درخواست‌های ۲۴ ساعت اخیر" value={data.requests_last_24h} />
        <Metric label="خطاهای ۲۴ ساعت اخیر" value={data.errors_last_24h} />
        <Metric label="نرخ خطا" value={`${(data.error_rate_24h * 100).toFixed(1)}%`} />
        <Metric label="میانگین تاخیر (ms)" value={data.avg_duration_ms_24h ?? "—"} />
      </div>
      <h4>پرتکرارترین عملیات (۲۴ ساعت اخیر)</h4>
      {data.top_actions_24h.length === 0 && <EmptyState text="داده‌ای ثبت نشده." />}
      {data.top_actions_24h.length > 0 && (
        <Table
          columns={[{ key: "action", header: "عملیات" }, { key: "calls", header: "تعداد" }]}
          rows={data.top_actions_24h}
        />
      )}
    </Card>
  );
}

function Metric({ label, value }) {
  return (
    <div className="card" style={{ margin: 0, textAlign: "center" }}>
      <div style={{ fontSize: "var(--font-size-xl)", fontWeight: "var(--font-weight-bold)" }}>{value}</div>
      <div className="muted">{label}</div>
    </div>
  );
}


function ModulesTab() {
  const [data, error, refresh] = useLoad(adminListModules, []);
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState("");
  const [completed, setCompleted] = useState("");
  const [readiness, setReadiness] = useState(null);
  const [readinessBusy, setReadinessBusy] = useState(null);

  function toggle(moduleId) {
    setSelected((current) => current.includes(moduleId)
      ? current.filter((id) => id !== moduleId)
      : [...current, moduleId]);
  }

  async function installSelected() {
    if (!selected.length || busy) return;
    setBusy("batch");
    setActionError("");
    setCompleted("");
    // One request per module makes dependency/install failures explicit and
    // prevents the UI from claiming an all-or-nothing batch succeeded.
    for (const moduleId of selected) {
      const module = data.modules.find((item) => item.id === moduleId);
      try {
        await adminInstallModule(moduleId);
        setCompleted((current) => `${current}${current ? "، " : ""}${module?.label || "برنامه"}`);
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : `نصب ${module?.label || "برنامه"} ناموفق بود`);
        break;
      }
    }
    setSelected([]);
    setBusy(null);
    refresh();
    window.dispatchEvent(new Event("modules:changed"));
  }

  async function showReadiness(module) {
    setReadinessBusy(module.id);
    setActionError("");
    try {
      setReadiness(await adminGetModuleReadiness(module.id));
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "خطا در بررسی آمادگی برنامه");
    } finally {
      setReadinessBusy(null);
    }
  }

  const stateLabel = {
    installed: "نصب‌شده",
    uninstalled: "آمادهٔ نصب",
    uninstallable: "روی این دستگاه قابل نصب نیست",
    "to install": "در صف نصب",
    "to upgrade": "در حال ارتقا",
    "to remove": "در حال حذف",
    installing: "در حال نصب",
  };
  const levelLabel = {
    discovered_read_only: "پایهٔ خواندن",
    reviewed_operational: "عملیاتیِ بررسی‌شده",
    blocked: "محدود تا بررسی",
  };
  const agentStateLabel = {
    connected: "متصل به ایجنت",
    connected_no_tools: "متصل؛ ابزار تاییدشده ندارد",
    error: "اتصال ایجنت نیازمند بررسی",
    disconnected: "به ایجنت متصل نیست",
  };

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <>
      <Card
        title="برنامه‌های سازمانی روی این دستگاه"
        actions={<Button size="sm" onClick={installSelected} loading={busy === "batch"} disabled={!selected.length || Boolean(busy)}>نصب موارد انتخاب‌شده</Button>}
      >
        <p className="muted">
          این فهرست مخصوص همین دستگاه و همین مشتری است. نصب هر برنامه از مسیر رسمی انجام می‌شود و بعد از آن، اتصال آن به ایجنت و رجیستری ابزارها به‌صورت خودکار انجام می‌شود؛ مدل محلی یک‌بار در سطح دستگاه provision می‌شود و برای هر برنامه دوباره دانلود نمی‌شود.
        </p>
        {completed && <Alert tone="success">نصب موفق: {completed}. همگام‌سازی منو و قابلیت‌ها به‌صورت خودکار در حال انجام است.</Alert>}
        {actionError && <Alert>{actionError}</Alert>}
        {!data.modules.length && <EmptyState text="برنامهٔ قابل ارائه‌ای روی این دستگاه پیدا نشد." />}
        {data.modules.length > 0 && (
          <Table
            columns={[
              {
                key: "select", header: "انتخاب",
                render: (module) => module.state === "installed" ? <Badge tone="success">فعال</Badge> : module.request?.state === "installing" ? <Badge tone="info">در حال نصب</Badge> : <input className="modules-checkbox" type="checkbox" checked={selected.includes(module.id)} onChange={() => toggle(module.id)} disabled={Boolean(busy) || module.state !== "uninstalled" || module.request?.state === "installing"} aria-label={`انتخاب ${module.label}`} />,
              },
              { key: "label", header: "برنامه" },
              { key: "category", header: "دسته‌بندی", render: (module) => module.category || "—" },
              { key: "state", header: "وضعیت", render: (module) => { const state = module.request?.state === "installing" ? "installing" : module.state; return <Badge tone={state === "installed" ? "success" : state === "uninstallable" ? "danger" : "info"}>{stateLabel[state] || state}</Badge>; } },
              { key: "dependencies", header: "پیش‌نیازها", render: (module) => module.dependencies.join("، ") || "—" },
              { key: "integration", header: "AI", render: (module) => {
                const agent = module.agent_connection || {};
                return <span>
                  {levelLabel[module.integration_level] || "در حال شناسایی"}
                  <small className="module-row-detail">{module.capability_count} قابلیت</small>
                  <small className={`module-row-detail ${agent.connected ? "module-agent-ok" : "module-agent-warning"}`}>
                    {agentStateLabel[agent.state] || "وضعیت اتصال نامشخص"}{agent.tool_count ? ` · ${agent.tool_count} ابزار` : ""}
                  </small>
                </span>;
              } },
              { key: "menu_count", header: "منو", render: (module) => module.state === "installed" ? `${module.menu_count}` : "پس از نصب" },
              { key: "readiness", header: "آمادگی", render: (module) => <Button size="sm" variant="ghost" loading={readinessBusy === module.id} onClick={() => showReadiness(module)}>بررسی</Button> },
            ]}
            rows={data.modules}
          />
        )}
      </Card>
      <Modal open={Boolean(readiness)} title={readiness?.module?.label ? `آمادگی: ${readiness.module.label}` : "آمادگی برنامه"} onClose={() => setReadiness(null)}>
        {readiness && <>
          <div className="setup-check-grid">
            {Object.entries(readiness.checks || {}).map(([key, ok]) => <SetupCheck key={key} label={key} ok={ok} />)}
          </div>
          <p className="muted">آماده برای تست داخلی: {readiness.ready_for_internal_test ? "بله" : "خیر"}</p>
          <p className="muted">آماده برای تحویل مشتری: {readiness.ready_for_customer_handoff ? "بله" : "خیر"}</p>
          <h4>پیش‌نیازها</h4>
          {(readiness.dependencies || []).map((dependency) => <p key={dependency.label}><Badge tone={dependency.state === "installed" ? "success" : "danger"}>{dependency.state}</Badge> {dependency.label}</p>)}
        </>}
      </Modal>
      <Card title="مرز امنیتی">
        <p className="muted">
          نصب یک برنامه، به‌معنی فعال‌شدن خودکار همهٔ عملیات AI آن نیست. خواندن، audit و event پایه خودکار است؛ عملیات مالی، حذف، تأیید و تغییرات حساس فقط با capability و adapter بررسی‌شده فعال می‌شوند.
        </p>
      </Card>
    </>
  );
}

function ControlPlaneTab() {
  const [data, error] = useLoad(() => fetch("/api/admin/control-plane", { credentials: "include" }).then(async r => { const j=await r.json(); if(!r.ok) throw new Error(j.error || "خطا"); return j; }), []);
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return <Card title="Customer Control Plane">
    <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))",gap:12}}>
      <Metric label="کاربران" value={data.users}/><Metric label="دپارتمان‌ها" value={data.departments}/><Metric label="موقعیت‌ها" value={data.positions}/><Metric label="Designerها" value={data.designers}/><Metric label="Access Review" value={data.access_reviews}/><Metric label="SCIM token فعال" value={data.scim_active_tokens}/>
    </div>
    <h4>بخش‌های فعال Control Plane</h4><p>{data.sections.join(" • ")}</p>
    <h4>SSO</h4><Table columns={[{key:"name",header:"Provider"},{key:"protocol",header:"Protocol"},{key:"active",header:"Active"}]} rows={data.sso || []}/>
    <h4>Configuration Profiles</h4><Table columns={[{key:"name",header:"Profile"},{key:"state",header:"State"},{key:"version",header:"Version"}]} rows={data.configuration_profiles || []}/>
  </Card>;
}
