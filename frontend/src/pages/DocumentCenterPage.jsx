import React, { useEffect, useState } from "react";
import {
  listDocuments, searchDocuments, uploadDocument, deleteDocument, reindexDocument,
  getDocumentOptions, ApiError,
} from "../api/client.js";
import {
  Card, Input, TextArea, Select, Button, Badge, Modal, Tabs, Alert,
  EmptyState, Spinner,
} from "../components";

// Document Center (roadmap #47) — replaces the old first-pass
// DocumentsPage.jsx. Same three-tier (actually four: company/
// department/group/personal, see company_document.py) access model
// the AI tools and /api/rpc already enforce; this page just gives a
// human a dedicated place to browse AND upload/delete by that same
// model, instead of going into the Odoo backend for anything beyond
// read-only browsing (the old page's only capability).

const ACCESS_LABEL = {
  company: "کل سازمان",
  department: "دپارتمان",
  group: "گروه محدود",
  personal: "شخصی",
};

const ACCESS_TONE = {
  company: "info",
  department: "warning",
  group: "neutral",
  personal: "success",
};

const INGESTION_LABEL = {
  no_file: "بدون فایل",
  pending: "در صف پردازش",
  extracting: "در حال استخراج",
  embedding: "در حال ایندکس معنایی",
  indexed: "قابل جستجو",
  empty: "بدون متن قابل استخراج",
  failed: "پردازش ناموفق",
};

const INGESTION_TONE = {
  no_file: "neutral",
  pending: "warning",
  extracting: "warning",
  embedding: "warning",
  indexed: "success",
  empty: "neutral",
  failed: "danger",
};

const TABS = [
  { key: "", label: "همه" },
  { key: "company", label: "کل سازمان" },
  { key: "department", label: "دپارتمانی" },
  { key: "group", label: "گروهی" },
  { key: "personal", label: "شخصی" },
];

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(new Error("خواندن فایل ناموفق بود"));
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
    name: "", description: "", access_level: "personal",
    department_id: "", group_id: "", file: null,
  });
  const [uploading, setUploading] = useState(false);
  const [reindexing, setReindexing] = useState(null);

  function refresh() {
    setDocuments(null);
    listDocuments("", tab)
      .then((data) => setDocuments(data.documents))
      .catch((err) => setError(err instanceof ApiError ? err.message : "خطا در بارگذاری"));
  }

  useEffect(refresh, [tab]);

  // Ingestion is asynchronous. Keep the badge useful without turning the
  // page into a busy loop: poll only while this tab contains an active job.
  useEffect(() => {
    const active = (documents || []).some((document) =>
      ["pending", "extracting", "embedding"].includes(document.ingestion_status)
    );
    if (!active) return undefined;
    const timer = setInterval(() => {
      listDocuments("", tab)
        .then((data) => setDocuments(data.documents))
        .catch(() => undefined);
    }, 3000);
    return () => clearInterval(timer);
  }, [documents, tab]);

  async function handleSemanticSearch(e) {
    e.preventDefault();
    if (!semanticQuery.trim()) return;
    setSearching(true);
    setError("");
    try {
      const data = await searchDocuments(semanticQuery, 5);
      setSemanticResults(data.results);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "جستجو ناموفق بود");
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
        .catch((err) => {
          setError(err instanceof ApiError ? err.message : "خطا در بارگذاری گزینه‌های دسترسی");
          setOptions({ departments: [], groups: [], own_department_id: null });
        });
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
      setError(err instanceof ApiError ? err.message : "آپلود ناموفق بود");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId) {
    try {
      await deleteDocument(documentId);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "حذف ناموفق بود");
    }
  }

  async function handleReindex(documentId) {
    setReindexing(documentId);
    setError("");
    try {
      await reindexDocument(documentId);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "تلاش مجدد ایندکس ناموفق بود");
    } finally {
      setReindexing(null);
    }
  }

  return (
    <div>
      <div className="ds-card-header" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>مرکز اسناد</h2>
        <Button size="sm" onClick={openUpload}>+ سند جدید</Button>
      </div>

      <Card title="جستجوی معنایی">
        <p className="muted">سوال بپرسید، نه فقط کلیدواژه - مثلاً «سیاست مرخصی برای روزهای استفاده‌نشده چیست»</p>
        <form onSubmit={handleSemanticSearch}>
          <Input
            value={semanticQuery}
            onChange={(e) => setSemanticQuery(e.target.value)}
            placeholder="سوال خود را بنویسید..."
          />
          <Button type="submit" loading={searching}>جستجو</Button>
        </form>
      </Card>

      <Alert>{error}</Alert>

      {semanticResults && (
        <Card title="نتایج جستجوی معنایی">
          {semanticResults.length === 0 && <EmptyState text="نتیجه‌ای یافت نشد." />}
          {semanticResults.map((r, i) => {
            const citation = r.citation || {};
            const anchors = [
              citation.page ? `صفحه ${citation.page}` : "",
              citation.section ? `بخش ${citation.section}` : "",
              citation.sheet ? `برگه ${citation.sheet}` : "",
              citation.slide ? `اسلاید ${citation.slide}` : "",
              citation.table ? `جدول ${citation.table}` : "",
            ].filter(Boolean);
            return (
              <div key={i} style={{ marginBottom: 12 }}>
                <div><strong>{r.document_name}</strong> <span className="muted">({r.relevance_score ?? r.similarity})</span></div>
                {anchors.length > 0 && <div className="muted" style={{ fontSize: 12 }}>{anchors.join(" — ")}</div>}
                <div className="muted">{r.excerpt.slice(0, 220)}...</div>
              </div>
            );
          })}
        </Card>
      )}

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {documents === null && <Spinner />}
      {documents && documents.length === 0 && <EmptyState text="سندی در این سطح دسترسی یافت نشد." />}

      {documents && documents.map((d) => (
        <Card key={d.id}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div>
                <strong>{d.name}</strong>{" "}
                <Badge tone={ACCESS_TONE[d.access_level]}>{ACCESS_LABEL[d.access_level]}</Badge>
                {d.file_name && (
                  <Badge tone={INGESTION_TONE[d.ingestion_status] || "neutral"}>
                    {INGESTION_LABEL[d.ingestion_status] || "وضعیت نامشخص"}
                  </Badge>
                )}
                {d.department && <span className="muted"> — {d.department}</span>}
                {d.group && <span className="muted"> — {d.group}</span>}
              </div>
              {d.description && <div className="muted">{d.description}</div>}
              {d.ingestion_error && <div className="muted">{d.ingestion_error}</div>}
              {d.ingestion_warnings && <div className="muted">هشدار استخراج: {d.ingestion_warnings}</div>}
              {d.ingestion_parser && (
                <div className="muted" style={{ fontSize: 12 }}>
                  parser: {d.ingestion_parser}{d.ingestion_pages ? ` — ${d.ingestion_pages} صفحه` : ""}
                </div>
              )}
              <div className="muted" style={{ fontSize: 12 }}>
                {d.owner ? `مالک: ${d.owner}` : ""} {d.file_name ? `— ${d.file_name}` : ""}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {d.ingestion_status === "failed" && (d.is_mine || user?.can_manage_documents) && (
                <Button size="sm" loading={reindexing === d.id} onClick={() => handleReindex(d.id)}>تلاش مجدد</Button>
              )}
              {(d.is_mine || user?.can_manage_documents) && (
                <Button variant="danger" size="sm" onClick={() => handleDelete(d.id)}>حذف</Button>
              )}
            </div>
          </div>
        </Card>
      ))}

      <Modal
        open={uploadOpen}
        title="آپلود سند جدید"
        onClose={() => setUploadOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setUploadOpen(false)}>انصراف</Button>
            <Button onClick={handleUpload} loading={uploading} disabled={!uploadForm.name}>ثبت</Button>
          </>
        }
      >
        <form onSubmit={handleUpload}>
          <Input
            label="نام سند" required value={uploadForm.name}
            onChange={(e) => setUploadForm({ ...uploadForm, name: e.target.value })}
          />
          <TextArea
            label="توضیح (اختیاری)" rows={2} value={uploadForm.description}
            onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })}
          />
          <Select
            label="سطح دسترسی" value={uploadForm.access_level}
            onChange={(e) => setUploadForm({ ...uploadForm, access_level: e.target.value })}
            options={[
              { value: "personal", label: "شخصی (فقط خودم)" },
              { value: "department", label: "دپارتمان" },
              { value: "group", label: "گروه محدود" },
              { value: "company", label: "کل سازمان" },
            ]}
          />
          {uploadForm.access_level === "department" && (
            <Select
              label="دپارتمان" value={uploadForm.department_id}
              onChange={(e) => setUploadForm({ ...uploadForm, department_id: e.target.value })}
              placeholder="انتخاب کنید..."
              options={(options?.departments || []).map((d) => ({ value: d.id, label: d.name }))}
            />
          )}
          {uploadForm.access_level === "group" && (
            <Select
              label="گروه" value={uploadForm.group_id}
              onChange={(e) => setUploadForm({ ...uploadForm, group_id: e.target.value })}
              placeholder="انتخاب کنید..."
              options={(options?.groups || []).map((g) => ({ value: g.id, label: g.name }))}
            />
          )}
          {uploadForm.access_level === "group" && options && options.groups.length === 0 && (
            <p className="muted">شما عضو هیچ گروه محدودی نیستید - فقط می‌توانید سطح دسترسی دیگری انتخاب کنید.</p>
          )}
          <Input
            label="فایل (اختیاری)" type="file"
            onChange={(e) => setUploadForm({ ...uploadForm, file: e.target.files?.[0] || null })}
          />
        </form>
      </Modal>
    </div>
  );
}
