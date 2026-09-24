import React, { useEffect, useState } from "react";
import * as api from "../api/client.js";
import { Alert, Badge, Card, EmptyState, Spinner } from "../components";

export default function AgentsPage() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getAgents().then((x) => setItems(x.agents || [])).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">AI Agents</div>
          <h1>Agents</h1>
          <p>Each role's agent works strictly inside that user's effective capabilities.</p>
        </div>
      </header>

      <Alert onDismiss={() => setError("")}>{error}</Alert>
      {items === null && !error && <Spinner />}

      {items && items.length === 0 && (
        <Card><EmptyState icon="bot" title="No agents" text="No agent has been registered yet." /></Card>
      )}

      {items && items.length > 0 && (
        <div className="tile-grid">
          {items.map((a) => (
            <Card hover key={a.id ?? a.name} className="tile-card">
              <span className="orb" style={{ width: 40, height: 40 }} />
              <h3>{a.name}</h3>
              <p>{a.description || "Role-aware enterprise agent"}</p>
              <div className="tile-actions">
                {a.tools != null && <Badge tone="neutral">{a.tools} tools</Badge>}
                <Badge tone="ok" dot>Policy bound</Badge>
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
