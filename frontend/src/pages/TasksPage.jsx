import React, { useEffect, useState } from "react";
import * as api from "../api/client.js";
import { Alert, Badge, Button, Card, EmptyState, Icon, Input, Spinner } from "../components";

const STATE_TONE = { open: "info", in_progress: "warn", done: "ok" };

export default function TasksPage() {
  const [tasks, setTasks] = useState(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => api.getTasks().then((x) => setTasks(x.tasks || [])).catch((e) => setError(e.message));
  useEffect(() => { setTasks(null); load(); }, []);

  async function create(e) {
    if (e) e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      await api.createTask({ name: name.trim() });
      setName("");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Work Management</div>
          <h1>Tasks</h1>
          <p>Everything the assistant and your team are working on, in one place.</p>
        </div>
      </header>

      <Card>
        <form className="h-stack" onSubmit={create}>
          <Input
            placeholder="Write a new task and press Enter…"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="New task title"
          />
          <Button variant="primary" icon="plus" type="submit" disabled={!name.trim()} loading={busy}>
            Add
          </Button>
        </form>
      </Card>

      <Alert onDismiss={() => setError("")}>{error}</Alert>

      {tasks === null && <Spinner />}
      {tasks && tasks.length === 0 && (
        <Card><EmptyState icon="tasks" title="No tasks yet" text="Create one above, or ask the assistant to do it from the chat." /></Card>
      )}

      {tasks && tasks.length > 0 && (
        <Card style={{ padding: "8px 14px" }}>
          {tasks.map((t) => (
            <div className="list-row" key={t.id}>
              <div className="icon-tile"><Icon name="tasks" size={18} /></div>
              <div className="grow">
                <div className="strong">{t.name}</div>
              </div>
              <Badge tone={STATE_TONE[t.state] || "neutral"} dot>{t.state || "open"}</Badge>
            </div>
          ))}
        </Card>
      )}
    </>
  );
}
