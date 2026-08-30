import React, { useEffect, useState } from "react";
import { listLeaves, createLeave, cancelLeave, ApiError } from "../api/client.js";
import { Card, Input, TextArea, Button, Badge, Alert, EmptyState, Spinner } from "../components";

const STATUS_LABEL = {
  draft: "پیش‌نویس",
  pending_approval: "در انتظار تایید",
  approved: "تایید شده",
  rejected: "رد شده",
  cancelled: "لغو شده",
};

const STATUS_TONE = {
  draft: "neutral",
  pending_approval: "warning",
  approved: "success",
  rejected: "danger",
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
      .catch((err) => setError(err instanceof ApiError ? err.message : "خطا در بارگذاری"));
  }

  useEffect(refresh, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await createLeave(form.date_from, form.date_to, form.reason);
      setForm({ date_from: "", date_to: "", reason: "" });
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ثبت درخواست ناموفق بود");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancel(leaveId) {
    try {
      await cancelLeave(leaveId);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "لغو ناموفق بود");
    }
  }

  return (
    <div>
      <h2>مرخصی‌های من</h2>

      <Card title="درخواست جدید">
        <form onSubmit={handleSubmit}>
          <Input
            type="date" required value={form.date_from} label="از تاریخ"
            onChange={(e) => setForm({ ...form, date_from: e.target.value })}
          />
          <Input
            type="date" required value={form.date_to} label="تا تاریخ"
            onChange={(e) => setForm({ ...form, date_to: e.target.value })}
          />
          <TextArea
            rows={2} placeholder="دلیل (اختیاری)" value={form.reason} label="دلیل"
            onChange={(e) => setForm({ ...form, reason: e.target.value })}
          />
          <Button type="submit" loading={submitting}>ثبت درخواست</Button>
        </form>
      </Card>

      <Alert>{error}</Alert>

      {leaves === null && <Spinner />}
      {leaves && leaves.length === 0 && <EmptyState text="درخواستی ثبت نشده." />}

      {leaves && leaves.map((leave) => (
        <Card key={leave.id}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <strong>{leave.date_from?.slice(0, 10)} تا {leave.date_to?.slice(0, 10)}</strong>
              <div className="muted">{leave.leave_type}{leave.reason ? ` — ${leave.reason}` : ""}</div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Badge tone={STATUS_TONE[leave.status] || "neutral"}>
                {STATUS_LABEL[leave.status] || leave.status}
              </Badge>
              {(leave.status === "draft" || leave.status === "pending_approval") && (
                <Button variant="danger" size="sm" onClick={() => handleCancel(leave.id)}>
                  لغو
                </Button>
              )}
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}
