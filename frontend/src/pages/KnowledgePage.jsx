import React from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card } from "../components";

export default function KnowledgePage() {
  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Knowledge</div>
          <h1>Knowledge</h1>
          <p>Organizational knowledge with the same ACL as your documents — the AI only sees what you may see.</p>
        </div>
      </header>

      <Card className="hero-card">
        <Badge tone="ok" dot>ACL protected</Badge>
        <h2>Knowledge you can trust</h2>
        <p>
          Personal, team, department and company documents can each be indexed
          into Knowledge on their own. Every answer the assistant gives from
          Knowledge respects exactly the same access boundaries.
        </p>
        <div className="mt-6">
          <Link to="/documents"><Button variant="primary" iconRight="arrowRight">Open Document Center</Button></Link>
        </div>
      </Card>

      <div className="stat-grid mt-6">
        <div className="stat"><b>4</b><span>Access scopes</span></div>
        <div className="stat"><b>ACL</b><span>Same as documents</span></div>
        <div className="stat"><b>AI</b><span>Answers within your rights</span></div>
      </div>
    </>
  );
}
