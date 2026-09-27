import React, { useEffect, useState } from "react";
import * as api from "../api/client.js";
import { Alert, Card, EmptyState, Icon, Spinner } from "../components";

export default function DepartmentsPage() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getDepartments().then((x) => setItems(x.departments || [])).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Organization</div>
          <h1>Departments</h1>
          <p>Each department gets its own chat, agent, documents, knowledge and workflows.</p>
        </div>
      </header>

      <Alert onDismiss={() => setError("")}>{error}</Alert>
      {items === null && !error && <Spinner />}

      {items && items.length === 0 && (
        <Card><EmptyState icon="building" title="No departments" text="No department is visible to your role." /></Card>
      )}

      {items && items.length > 0 && (
        <div className="tile-grid">
          {items.map((d) => (
            <Card hover key={d.id} className="tile-card">
              <div className="icon-tile grad"><Icon name="building" size={20} /></div>
              <h3>{d.name}</h3>
              <p>{d.member_count} members</p>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
