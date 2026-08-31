import React, { useEffect, useState } from "react";
import {
  adminListRoles, adminListUsers, adminListAccessGrants, adminCreateAccessGrant,
  adminRevokeAccessGrant, adminListDocuments, adminListAgents, adminGetBranding,
  adminUpdateBranding, adminGetMetrics, ApiError,
} from "../api/client.js";
import {
  Card, Table, Badge, Button, Tabs, Alert, Spinner, EmptyState, Modal, Select, Input,
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
  { key: "roles", label: "نقش‌ها" },
  { key: "grants", label: "دسترسی موقت / تفویض" },
  { key: "documents", label: "اسناد" },
  { key: "agents", label: "ایجنت‌ها" },
  { key: "branding", label: "برندینگ" },
  { key: "observability", label: "مانیتورینگ" },
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
      {tab === "roles" && <RolesTab />}
      {tab === "grants" && <GrantsTab />}
      {tab === "documents" && <DocumentsTab />}
      {tab === "agents" && <AgentsTab />}
      {tab === "branding" && <BrandingTab />}
      {tab === "observability" && <ObservabilityTab />}
      {tab === "control" && <ControlPlaneTab />}
    </div>
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
    if (!users) adminListUsers().then((d) => setUsers(d.users)).catch(() => setUsers([]));
    if (!roles) adminListRoles().then((d) => setRoles(d.roles)).catch(() => setRoles([]));
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

// --- Branding (#55) --------------------------------------------------------
function BrandingTab() {
  const [data, error, refresh] = useLoad(adminGetBranding, []);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data && !form) setForm({ brand_name: data.brand_name, brand_domain: data.brand_domain });
  }, [data]);

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setSaveError("");
    setSaved(false);
    try {
      await adminUpdateBranding(form);
      setSaved(true);
      refresh();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "ذخیره ناموفق بود");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <Alert>{error}</Alert>;
  if (!data || !form) return <Spinner />;

  return (
    <Card title="تنظیمات برند (White-label، مورد #55)">
      <p className="muted">
        شرکت فعلی: {data.company_name} — لوگو: {data.has_logo ? "تنظیم شده" : "تنظیم نشده"}
      </p>
      <form onSubmit={handleSave}>
        <Input
          label="نام برند" value={form.brand_name}
          onChange={(e) => setForm({ ...form, brand_name: e.target.value })}
        />
        <Input
          label="دامنه‌ی برند" value={form.brand_domain}
          onChange={(e) => setForm({ ...form, brand_domain: e.target.value })}
        />
        {saved && <Alert tone="success">تنظیمات ذخیره شد.</Alert>}
        <Alert>{saveError}</Alert>
        <Button type="submit" loading={saving}>ذخیره</Button>
      </form>
      <p className="muted" style={{ marginTop: 12 }}>
        نام برند از Configuration و QWeb template inheritance اعمال می‌شود؛ JS فقط fallback برای
        محتوای پویاست و منبع اصلی white-label نیست.
      </p>
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
