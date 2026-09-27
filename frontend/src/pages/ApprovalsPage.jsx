import React, { useEffect, useState } from "react";
import * as api from "../api/client.js";
import { Alert, Badge, Card, Spinner, Table } from "../components";

export default function ApprovalsPage() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getApprovals().then((x) => setItems(x.approvals || [])).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Control</div>
          <h1>Approvals</h1>
          <p>Sensitive operations pause here until policy and role checks pass.</p>
        </div>
      </header>

      <Alert onDismiss={() => setError("")}>{error}</Alert>
      {items === null && !error && <Spinner />}

      {items && (
        <Card>
          <Table
            emptyText="Nothing waiting for your approval."
            columns={[
              { key: "name", header: "Request" },
              { key: "requester", header: "Requested by" },
              {
                key: "risk", header: "Risk",
                render: (a) => <Badge tone={(a.risk ?? 0) > 70 ? "err" : "warn"} dot>{a.risk ?? 0}</Badge>,
              },
              { key: "state", header: "Status", render: (a) => <Badge tone="info">{a.state || "pending"}</Badge> },
            ]}
            rows={items}
          />
        </Card>
      )}
    </>
  );
}
