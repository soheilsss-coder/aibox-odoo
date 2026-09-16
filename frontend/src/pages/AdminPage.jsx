import React, { useEffect, useState } from "react";
import {
  adminListRoles, adminListUsers, adminListAccessGrants, adminCreateAccessGrant,
  adminRevokeAccessGrant, adminListDocuments, adminListAgents, adminGetBranding,
  adminUpdateBranding, adminGetMetrics, ApiError,
} from "../api/client.js";
import { Alert, Badge, Button, Card, EmptyState, Icon, Input, Modal, Select, Spinner, Table, Tabs, TextArea } from "../components";

// Admin Console — read (and, for grants/branding, write) views over the
// /api/admin/* surface. Visibility is gated upstream by the
// admin.console.read capability; every API call re-checks server-side.

const TABS = [
  { key: "roles", label: "Roles" },
  { key: "grants", label: "Access grants" },
  { key: "documents", label: "Documents" },
  { key: "agents", label: "Agents" },
  { key: "branding", label: "Branding" },
  { key: "observability", label: "Monitoring" },
  { key: "control", label: "Control Plane" },
];

function useLoad(fn, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = () => fn().then(setData).catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load."));
  useEffect(load, deps);
  return [data, error, load];
}

export default function AdminPage() {
  const [tab, setTab] = useState("roles");
  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Administration</div>
          <h1>Admin Console</h1>
          <p>Roles, temporary access, documents, agents, branding and runtime health.</p>
        </div>
      </header>
      <div className="mb-6"><Tabs tabs={TABS} active={tab} onChange={setTab} /></div>
      {tab === "roles" && <RolesTab />}
      {tab === "grants" && <GrantsTab />}
      {tab === "documents" && <DocumentsTab />}
      {tab === "agents" && <AgentsTab />}
      {tab === "branding" && <BrandingTab />}
      {tab === "observability" && <ObservabilityTab />}
      {tab === "control" && <ControlPlaneTab />}
    </>
  );
}

/* --- Roles ------------------------------------------------------------ */
function RolesTab() {
  const [data, error] = useLoad(adminListRoles, []);
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <Card title="Roles and members">
      <Table
        emptyText="No roles defined."
        columns={[
          { key: "name", header: "Role" },
          { key: "comment", header: "Description" },
          { key: "implied_roles", header: "Base groups", render: (r) => r.implied_roles.join(", ") || "—" },
          { key: "member_count", header: "Members", width: 90 },
          { key: "members", header: "People", render: (r) => r.members.map((m) => m.name).join(", ") || "—" },
        ]}
        rows={data.roles}
      />
    </Card>
  );
}

/* --- Access grants ----------------------------------------------------- */
const GRANT_STATE_TONE = { active: "ok", expired: "neutral", revoked: "err" };
const GRANT_STATE_LABEL = { active: "Active", expired: "Expired", revoked: "Revoked" };

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
        group_id: form.group_id || "",
        expires_on: form.expires_on || null,
        reason: form.reason,
      });
      setOpen(false);
      setForm({ to_user_id: "", group_id: "", expires_on: "", reason: "" });
      refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create the grant.");
    } finally {
      setSaving(false);
    }
  }

  async function handleRevoke(grantId) {
    try {
      await adminRevokeAccessGrant(grantId);
      refresh();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not revoke.");
    }
  }

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <Card
      title="Temporary / delegated access"
      actions={<Button variant="primary" size="sm" icon="plus" onClick={openModal}>New grant</Button>}
    >
      <Alert>{formError}</Alert>
      <Table
        emptyText="No active delegations."
        columns={[
          { key: "to_user", header: "User" },
          { key: "role", header: "Role" },
          { key: "delegated_from", header: "Delegated from", render: (g) => g.delegated_from || "—" },
          { key: "expires_on", header: "Expires" },
          { key: "state", header: "Status", render: (g) => <Badge tone={GRANT_STATE_TONE[g.state]} dot>{GRANT_STATE_LABEL[g.state] || g.state}</Badge> },
          {
            key: "actions", header: "", width: 110,
            render: (g) => g.state === "active"
              ? <Button variant="danger" size="sm" onClick={() => handleRevoke(g.id)}>Revoke</Button>
              : null,
          },
        ]}
        rows={data.grants}
      />

      <Modal
        open={open}
        title="New access grant"
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={handleCreate} loading={saving} disabled={!form.to_user_id}>Create</Button>
          </>
        }
      >
        <form onSubmit={handleCreate}>
          <Select id="grant-user" label="User" value={form.to_user_id}
            onChange={(e) => setForm({ ...form, to_user_id: e.target.value })}
            placeholder="Choose…"
            options={(users || []).map((u) => ({ value: u.id, label: `${u.name} (${u.login})` }))} />
          <Select id="grant-role" label="Role" value={form.group_id}
            onChange={(e) => setForm({ ...form, group_id: e.target.value })}
            placeholder="Choose…"
            options={(roles || []).map((r, i) => ({ value: r.id ?? i, label: r.name }))} />
          <Input id="grant-expiry" type="date" label="Expires on (optional)" value={form.expires_on}
            onChange={(e) => setForm({ ...form, expires_on: e.target.value })} />
          <TextArea id="grant-reason" rows={2} label="Reason (optional)" value={form.reason}
            onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        </form>
      </Modal>
    </Card>
  );
}

/* --- Documents --------------------------------------------------------- */
const ACCESS_LABEL = { company: "Company", department: "Department", group: "Group", personal: "Personal" };

function DocumentsTab() {
  const [data, error] = useLoad(adminListDocuments, []);
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <Card title="All documents (admin view)">
      <Table
        emptyText="No documents in the system."
        columns={[
          { key: "name", header: "Name" },
          { key: "access_level", header: "Scope", render: (d) => <Badge>{ACCESS_LABEL[d.access_level] || d.access_level}</Badge> },
          { key: "department", header: "Department", render: (d) => d.department || "—" },
          { key: "group", header: "Group", render: (d) => d.group || "—" },
          { key: "owner", header: "Owner", render: (d) => d.owner || "—" },
          { key: "create_date", header: "Created", render: (d) => (d.create_date || "").slice(0, 10) },
        ]}
        rows={data.documents}
      />
    </Card>
  );
}

/* --- Agents ------------------------------------------------------------ */
const RISK_TONE = (n) => (n >= 70 ? "err" : n >= 40 ? "warn" : "ok");

function AgentsTab() {
  const [data, error] = useLoad(adminListAgents, []);
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <>
      <Card title="Agents">
        <Table
          emptyText="No agents registered."
          columns={[
            { key: "name", header: "Name" },
            { key: "model", header: "Model", render: (a) => a.model || "—" },
            { key: "provider", header: "Provider", render: (a) => a.provider || "—" },
            { key: "tool_count", header: "Tools", width: 80 },
            { key: "active", header: "Active", render: (a) => <Badge tone={a.active ? "ok" : "neutral"} dot>{a.active ? "Yes" : "No"}</Badge> },
          ]}
          rows={data.agents}
        />
      </Card>
      {data.tools && data.tools.length > 0 && (
        <Card title="Tools and risk gates">
          <Table
            columns={[
              { key: "name", header: "Tool" },
              { key: "risk_level", header: "Risk", render: (t) => <Badge tone={RISK_TONE(t.risk_level)} dot>RISK {t.risk_level}</Badge> },
              { key: "requires_approval_from", header: "Needs approval", render: (t) => t.requires_approval_from || "—" },
              { key: "description", header: "Description" },
            ]}
            rows={data.tools}
          />
        </Card>
      )}
    </>
  );
}

/* --- Branding ---------------------------------------------------------- */
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
      setSaveError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <Alert>{error}</Alert>;
  if (!data || !form) return <Spinner />;

  return (
    <Card title="Brand settings (white-label)">
      <p className="muted small mb-4">
        Current company: <strong className="strong">{data.company_name}</strong> · Logo: {data.has_logo ? "set" : "not set"}
      </p>
      <form onSubmit={handleSave}>
        <Input id="brand-name" label="Brand name" value={form.brand_name}
          onChange={(e) => setForm({ ...form, brand_name: e.target.value })} />
        <Input id="brand-domain" label="Brand domain" value={form.brand_domain}
          onChange={(e) => setForm({ ...form, brand_domain: e.target.value })} />
        {saved && <Alert tone="ok">Settings saved.</Alert>}
        <Alert>{saveError}</Alert>
        <Button variant="primary" type="submit" loading={saving} icon="check">Save</Button>
      </form>
    </Card>
  );
}

/* --- Observability ----------------------------------------------------- */
function ObservabilityTab() {
  const [data, error, refresh] = useLoad(adminGetMetrics, []);
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <Card title="Runtime metrics (/api/metrics)" actions={<Button size="sm" variant="soft" icon="refresh" onClick={refresh}>Refresh</Button>}>
      <div className="stat-grid">
        <Metric label="Requests (1h)" value={data.requests_last_hour} />
        <Metric label="Requests (24h)" value={data.requests_last_24h} />
        <Metric label="Errors (24h)" value={data.errors_last_24h} />
        <Metric label="Error rate" value={`${(data.error_rate_24h * 100).toFixed(1)}%`} />
        <Metric label="Avg latency (ms)" value={data.avg_duration_ms_24h ?? "—"} />
      </div>
      <h4 className="mt-6 mb-4">Most-called operations (24h)</h4>
      <Table
        emptyText="Nothing recorded yet."
        columns={[{ key: "action", header: "Operation" }, { key: "calls", header: "Calls", width: 90 }]}
        rows={data.top_actions_24h}
      />
    </Card>
  );
}

function Metric({ label, value }) {
  return (
    <div className="stat">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

/* --- Control Plane ------------------------------------------------------ */
function ControlPlaneTab() {
  const [data, error] = useLoad(
    () => fetch("/api/admin/control-plane", { credentials: "include" }).then(async (r) => {
      const j = await r.json();
      if (!r.ok) throw new ApiError(j.error || "Failed to load.", r.status);
      return j;
    }),
    []
  );
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <Card title="Customer Control Plane">
      <div className="stat-grid">
        <Metric label="Users" value={data.users} />
        <Metric label="Departments" value={data.departments} />
        <Metric label="Positions" value={data.positions} />
        <Metric label="Designers" value={data.designers} />
        <Metric label="Access reviews" value={data.access_reviews} />
        <Metric label="Active SCIM tokens" value={data.scim_active_tokens} />
      </div>
      {data.sections?.length > 0 && (
        <>
          <h4 className="mt-6 mb-4">Enabled sections</h4>
          <p className="muted small">{data.sections.join(" · ")}</p>
        </>
      )}
      <h4 className="mt-6 mb-4">SSO</h4>
      <Table
        emptyText="No SSO providers configured."
        columns={[{ key: "name", header: "Provider" }, { key: "protocol", header: "Protocol" }, { key: "active", header: "Active", render: (s) => <Badge tone={s.active ? "ok" : "neutral"} dot>{s.active ? "Yes" : "No"}</Badge> }]}
        rows={data.sso || []}
      />
      <h4 className="mt-6 mb-4">Configuration profiles</h4>
      <Table
        emptyText="No configuration profiles."
        columns={[{ key: "name", header: "Profile" }, { key: "state", header: "State" }, { key: "version", header: "Version" }]}
        rows={data.configuration_profiles || []}
      />
    </Card>
  );
}
