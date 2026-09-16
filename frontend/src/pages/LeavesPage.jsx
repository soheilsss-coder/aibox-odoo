import React, { useEffect, useState } from "react";
import { listLeaves, createLeave, cancelLeave, ApiError } from "../api/client.js";
import { Alert, Badge, Button, Card, EmptyState, Icon, Input, Spinner, TextArea } from "../components";

const STATUS_LABEL = {
  draft: "Draft",
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
  cancelled: "Cancelled",
};
const STATUS_TONE = {
  draft: "neutral",
  pending_approval: "warn",
  approved: "ok",
  rejected: "err",
  cancelled: "neutral",
};

export default function LeavesPage() {
  const [leaves, setLeaves] = useState(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ date_from: "", date_to: "", reason: "" });
  const [submitting, setSubmitting] = useState(false);

  function refresh() {
    listLeaves()
      .then((data) => setLeaves(data.leaves))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load."));
  }
  useEffect(() => { refresh(); }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await createLeave(form.date_from, form.date_to, form.reason);
      setForm({ date_from: "", date_to: "", reason: "" });
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not submit the request.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancel(leaveId) {
    try {
      await cancelLeave(leaveId);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not cancel.");
    }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">HR</div>
          <h1>My leave</h1>
          <p>Request time off — it flows through Odoo's own approval to your manager.</p>
        </div>
      </header>

      <Card title="New request">
        <form onSubmit={handleSubmit}>
          <div className="h-stack wrap" style={{ alignItems: "flex-start" }}>
            <div className="grow" style={{ minWidth: 170 }}>
              <Input id="lv-from" type="date" required label="From" value={form.date_from}
                onChange={(e) => setForm({ ...form, date_from: e.target.value })} />
            </div>
            <div className="grow" style={{ minWidth: 170 }}>
              <Input id="lv-to" type="date" required label="To" value={form.date_to}
                onChange={(e) => setForm({ ...form, date_to: e.target.value })} />
            </div>
          </div>
          <TextArea id="lv-reason" rows={2} label="Reason (optional)" value={form.reason}
            onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <Button variant="primary" type="submit" loading={submitting}>Submit request</Button>
        </form>
      </Card>

      <Alert onDismiss={() => setError("")}>{error}</Alert>

      {leaves === null && !error && <Spinner />}
      {leaves && leaves.length === 0 && (
        <Card><EmptyState icon="clock" title="No requests" text="You have not submitted a leave request yet." /></Card>
      )}

      {leaves && leaves.length > 0 && (
        <Card style={{ padding: "8px 14px" }}>
          {leaves.map((leave) => (
            <div className="list-row" key={leave.id}>
              <div className="icon-tile"><Icon name="clock" size={18} /></div>
              <div className="grow">
                <div className="strong">{leave.date_from?.slice(0, 10)} → {leave.date_to?.slice(0, 10)}</div>
                <div className="muted small">{leave.leave_type}{leave.reason ? ` — ${leave.reason}` : ""}</div>
              </div>
              <Badge tone={STATUS_TONE[leave.status] || "neutral"} dot>
                {STATUS_LABEL[leave.status] || leave.status}
              </Badge>
              {(leave.status === "draft" || leave.status === "pending_approval") && (
                <Button variant="danger" size="sm" onClick={() => handleCancel(leave.id)}>Cancel</Button>
              )}
            </div>
          ))}
        </Card>
      )}
    </>
  );
}
