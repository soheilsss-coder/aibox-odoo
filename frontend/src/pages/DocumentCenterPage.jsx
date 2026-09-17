import React, { useEffect, useState } from "react";
import {
  listDocuments, searchDocuments, uploadDocument, deleteDocument,
  getDocumentOptions, ApiError,
} from "../api/client.js";
import {
  Alert, Badge, Button, Card, EmptyState, Icon, Input, Modal,
  Select, Spinner, Tabs, TextArea,
} from "../components";

// Document Center — browse / search / upload / delete over the same
// company/department/group/personal ACL the AI tools enforce. The delete
// button mirrors the backend rule: own documents, or any document when the
// user holds the document.admin.manage capability.
const ACCESS_LABEL = { company: "Company-wide", department: "Department", group: "Restricted group", personal: "Personal" };
const ACCESS_TONE = { company: "info", department: "warn", group: "neutral", personal: "ok" };
const TABS = [
  { key: "", label: "All" },
  { key: "company", label: "Company" },
  { key: "department", label: "Department" },
  { key: "group", label: "Group" },
  { key: "personal", label: "Personal" },
];

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("Could not read the file."));
    reader.readAsDataURL(file);
  });
}

export default function DocumentCenterPage({ user }) {
  const [tab, setTab] = useState("");
  const [documents, setDocuments] = useState(null);
  const [error, setError] = useState("");

  const [semanticQuery, setSemanticQuery] = useState("");
  const [semanticResults, setSemanticResults] = useState(null);
  const [searching, setSearching] = useState(false);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [options, setOptions] = useState(null);
  const [uploadForm, setUploadForm] = useState({
    name: "", description: "", access_level: "personal", department_id: "", group_id: "", file: null,
  });
  const [uploading, setUploading] = useState(false);

  const capabilities = (user && user.capabilities) || [];
  const isAdmin = capabilities.includes("document.admin.manage");

  function refresh() {
    setDocuments(null);
    listDocuments("", tab)
      .then((data) => setDocuments(data.documents))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load."));
  }
  useEffect(() => { refresh(); }, [tab]);

  async function handleSemanticSearch(e) {
    e.preventDefault();
    if (!semanticQuery.trim()) return;
    setSearching(true);
    setError("");
    try {
      const data = await searchDocuments(semanticQuery, 5);
      setSemanticResults(data.results);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed.");
      setSemanticResults(null);
    } finally {
      setSearching(false);
    }
  }

  function openUpload() {
    setError("");
    setUploadOpen(true);
    if (!options) {
      getDocumentOptions()
        .then((data) => {
          setOptions(data);
          setUploadForm((f) => ({ ...f, department_id: data.own_department_id || "" }));
        })
        .catch(() => setOptions({ departments: [], groups: [], own_department_id: null }));
    }
  }

  async function handleUpload(e) {
    e.preventDefault();
    setUploading(true);
    setError("");
    try {
      const payload = {
        name: uploadForm.name,
        description: uploadForm.description,
        access_level: uploadForm.access_level,
      };
      if (uploadForm.access_level === "department") payload.department_id = Number(uploadForm.department_id);
      if (uploadForm.access_level === "group") payload.group_id = Number(uploadForm.group_id);
      if (uploadForm.file) {
        payload.file_base64 = await fileToBase64(uploadForm.file);
        payload.file_name = uploadForm.file.name;
      }
      await uploadDocument(payload);
      setUploadOpen(false);
      setUploadForm({ name: "", description: "", access_level: "personal", department_id: "", group_id: "", file: null });
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId) {
    try {
      await deleteDocument(documentId);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed.");
    }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Documents</div>
          <h1>Document Center</h1>
          <p>Browse, upload and manage documents within your access scopes.</p>
        </div>
        <Button variant="primary" icon="plus" onClick={openUpload}>New document</Button>
      </header>

      <Card title="Semantic search">
        <p className="muted small" style={{ marginBottom: 12 }}>
          Ask a question, not just keywords — e.g. “what is the policy on unused leave days?”
        </p>
        <form onSubmit={handleSemanticSearch} className="h-stack">
          <Input
            placeholder="Ask across the documents you can see…"
            value={semanticQuery}
            onChange={(e) => setSemanticQuery(e.target.value)}
            aria-label="Semantic search"
          />
          <Button variant="primary" icon="search" type="submit" loading={searching}>Search</Button>
        </form>
      </Card>

      <Alert onDismiss={() => setError("")}>{error}</Alert>

      {semanticResults && (
        <Card title="Results">
          {semanticResults.length === 0 && <EmptyState icon="search" text="No matching documents found." />}
          {semanticResults.map((r, i) => (
            <div key={i} style={{ marginBottom: 14 }}>
              <div className="h-stack" style={{ gap: 8 }}>
                <strong>{r.document_name}</strong>
                <Badge tone="accent">{Math.round(Number(r.similarity) * 100)}% match</Badge>
              </div>
              <div className="muted small mt-2">{String(r.excerpt).slice(0, 220)}…</div>
            </div>
          ))}
        </Card>
      )}

      <div className="mb-4" style={{ marginTop: 18 }}>
        <Tabs tabs={TABS} active={tab} onChange={setTab} />
      </div>

      {documents === null && <Spinner />}
      {documents && documents.length === 0 && (
        <Card><EmptyState icon="file" title="Nothing here" text="No document exists at this access level." /></Card>
      )}

      {documents && documents.length > 0 && (
        <Card style={{ padding: "8px 14px" }}>
          {documents.map((d) => (
            <div className="list-row" key={d.id}>
              <div className="icon-tile"><Icon name="file" size={18} /></div>
              <div className="grow">
                <div className="h-stack" style={{ gap: 8, flexWrap: "wrap" }}>
                  <strong>{d.name}</strong>
                  <Badge tone={ACCESS_TONE[d.access_level]}>{ACCESS_LABEL[d.access_level] || d.access_level}</Badge>
                  {d.department && <span className="muted small">· {d.department}</span>}
                  {d.group && <span className="muted small">· {d.group}</span>}
                </div>
                {d.description && <div className="muted small">{d.description}</div>}
                <div className="faint xsmall mt-2">
                  {d.owner ? `Owner: ${d.owner}` : ""}{d.file_name ? ` · ${d.file_name}` : ""}
                </div>
              </div>
              {(d.is_mine || isAdmin) && (
                <Button variant="danger" size="sm" icon="trash" onClick={() => handleDelete(d.id)}>Delete</Button>
              )}
            </div>
          ))}
        </Card>
      )}

      <Modal
        open={uploadOpen}
        title="Upload a document"
        onClose={() => setUploadOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setUploadOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={handleUpload} loading={uploading} disabled={!uploadForm.name}>Save</Button>
          </>
        }
      >
        <form onSubmit={handleUpload}>
          <Input id="doc-name" label="Name" required value={uploadForm.name}
            onChange={(e) => setUploadForm({ ...uploadForm, name: e.target.value })} />
          <TextArea id="doc-desc" label="Description (optional)" rows={2} value={uploadForm.description}
            onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })} />
          <Select id="doc-access" label="Access level" value={uploadForm.access_level}
            onChange={(e) => setUploadForm({ ...uploadForm, access_level: e.target.value })}
            options={[
              { value: "personal", label: "Personal (only me)" },
              { value: "department", label: "Department" },
              { value: "group", label: "Restricted group" },
              { value: "company", label: "Company-wide" },
            ]} />
          {uploadForm.access_level === "department" && (
            <Select id="doc-dept" label="Department" value={uploadForm.department_id}
              onChange={(e) => setUploadForm({ ...uploadForm, department_id: e.target.value })}
              placeholder="Choose…"
              options={(options?.departments || []).map((d) => ({ value: d.id, label: d.name }))} />
          )}
          {uploadForm.access_level === "group" && (
            <Select id="doc-group" label="Group" value={uploadForm.group_id}
              onChange={(e) => setUploadForm({ ...uploadForm, group_id: e.target.value })}
              placeholder="Choose…"
              options={(options?.groups || []).map((g) => ({ value: g.id, label: g.name }))} />
          )}
          {uploadForm.access_level === "group" && options && options.groups.length === 0 && (
            <p className="muted small">You are not a member of any restricted group — pick another access level.</p>
          )}
          <Input id="doc-file" label="File (optional)" type="file"
            onChange={(e) => setUploadForm({ ...uploadForm, file: e.target.files?.[0] || null })} />
        </form>
      </Modal>
    </>
  );
}
