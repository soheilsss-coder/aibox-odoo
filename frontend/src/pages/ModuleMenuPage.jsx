import React, { useEffect, useState } from "react";
import { useParams, NavLink } from "react-router-dom";
import { getModuleMenu, ApiError } from "../api/client.js";
import { Card, Table, Alert, Spinner, EmptyState, Badge } from "../components";

function displayValue(value) {
  if (value === null || value === undefined || value === false) return "—";
  if (typeof value === "object") return value.display_name || value.name || value[1] || "—";
  return String(value);
}

export default function ModuleMenuPage() {
  const { menuId, moduleId } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getModuleMenu(menuId)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "خطا در بارگذاری این بخش"));
  }, [menuId]);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;

  return (
    <div>
      <header className="page-head">
        <div>
          <div className="eyebrow">BUSINESS WORKSPACE</div>
          <h1>{data.title}</h1>
          <p>{data.message || "اطلاعات این بخش بر اساس دسترسی شما نمایش داده می‌شود."}</p>
        </div>
        <NavLink className="ghost-btn" to={`/modules/${moduleId}`}>بازگشت به برنامه</NavLink>
      </header>
      <Card title="داده‌های واقعی">
        {data.read_only && <p className="module-readonly-note"><Badge tone="info">خواندنی</Badge> تغییرات حساس از مسیر AI و عملیات بررسی‌شده انجام می‌شوند.</p>}
        {!data.columns?.length ? <EmptyState text={data.message || "نمایی برای نمایش وجود ندارد."} /> : !data.rows?.length ? <EmptyState text="رکوردی برای نمایش وجود ندارد." /> : (
          <Table
            columns={data.columns.map((column, index) => ({
              key: column.key || String(index),
              header: column.label,
              render: (row) => displayValue(row.values[index]),
            }))}
            rows={data.rows}
          />
        )}
      </Card>
      <Card title="اقدام با AI">
        <p className="muted">برای ایجاد یا تغییر رکورد، درخواست خود را در AI Workspace بنویسید. دسترسی، ریسک و نیاز به تأیید قبل از اجرا بررسی می‌شود.</p>
        <NavLink className="primary-btn" to="/chat">رفتن به AI Workspace</NavLink>
      </Card>
    </div>
  );
}
