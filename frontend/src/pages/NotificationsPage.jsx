import React, { useEffect, useState } from "react";
import * as api from "../api/client.js";
import { Alert, Card, EmptyState, Spinner } from "../components";

function fmtDate(v) {
  if (!v) return "";
  const d = new Date(String(v).replace(" ", "T") + "Z");
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function NotificationsPage() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getNotifications().then((x) => setItems(x.notifications || [])).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Inbox</div>
          <h1>Notifications</h1>
          <p>Events from tasks, approvals, documents, security and the AI.</p>
        </div>
      </header>

      <Alert onDismiss={() => setError("")}>{error}</Alert>
      {items === null && !error && <Spinner />}

      {items && items.length === 0 && (
        <Card><EmptyState icon="bell" title="All caught up" text="You have no new notifications." /></Card>
      )}

      {items && items.length > 0 && (
        <Card style={{ padding: "6px 10px" }}>
          {items.map((n) => (
            <div className={`notif ${n.is_read ? "" : "unread"}`} key={n.id}>
              <span className="notif-dot" />
              <div>
                <strong>{n.subject || "Notification"}</strong>
                {/* Body is authored server-side by trusted notification flows. */}
                <p dangerouslySetInnerHTML={{ __html: n.body || "" }} />
                <small>{fmtDate(n.date)}</small>
              </div>
            </div>
          ))}
        </Card>
      )}
    </>
  );
}
