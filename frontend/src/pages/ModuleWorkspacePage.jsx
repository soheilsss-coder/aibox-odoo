import React, { useEffect, useMemo, useState } from "react";
import { useParams, NavLink } from "react-router-dom";
import { getModuleNavigation, ApiError } from "../api/client.js";
import { Card, Badge, Alert, Spinner, EmptyState } from "../components";

const STATUS_LABEL = {
  discovered_read_only: "پایهٔ خواندن فعال است",
  reviewed_operational: "عملیات بررسی‌شده فعال است",
  blocked: "نیازمند بررسی",
};

const CERT_LABEL = {
  discovered: "شناسایی‌شده",
  baseline_ready: "پایه آماده",
  adapter_required: "عملیات حساس هنوز محدود است",
  runtime_certified: "تأییدشده در runtime",
  blocked: "مسدود",
};

function MenuTree({ menus, moduleId }) {
  const roots = menus.filter((item) => !item.parent_id || !menus.some((p) => p.id === item.parent_id));
  const children = (parentId) => menus.filter((item) => item.parent_id === parentId);
  const render = (item) => (
    <li key={item.id}>
      {item.has_action ? <NavLink className="module-menu-item module-menu-link" to={`/modules/${moduleId}/menus/${item.id}`}>
        <span>{item.label}</span>
        <small>بازکردن</small>
      </NavLink> : <div className="module-menu-item">
        <span>{item.label}</span>
        <small>منو</small>
      </div>}
      {children(item.id).length > 0 && <ul>{children(item.id).map(render)}</ul>}
    </li>
  );
  if (!roots.length) return <EmptyState text="منوی قابل نمایشی برای این کاربر وجود ندارد." />;
  return <ul className="module-menu-tree">{roots.map(render)}</ul>;
}

export default function ModuleWorkspacePage() {
  const { moduleId } = useParams();
  const [modules, setModules] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getModuleNavigation()
      .then((data) => setModules(data.modules || []))
      .catch((err) => setError(err instanceof ApiError ? err.message : "خطا در بارگذاری برنامه"));
  }, [moduleId]);

  const module = useMemo(
    () => modules?.find((item) => String(item.id) === String(moduleId)),
    [modules, moduleId],
  );

  if (error) return <Alert>{error}</Alert>;
  if (!modules) return <Spinner />;
  if (!module) return <EmptyState text="این برنامه برای حساب کاربری شما فعال نیست." />;

  const operational = module.integration_level === "reviewed_operational";
  return (
    <div>
      <header className="page-head">
        <div>
          <div className="eyebrow">BUSINESS APP</div>
          <h1>{module.label}</h1>
          <p>منوها و قابلیت‌های مجاز این برنامه از داده‌های واقعی سازمان شما خوانده می‌شوند.</p>
        </div>
        <NavLink className="primary-btn" to="/chat">پرسش از AI ←</NavLink>
      </header>

      <div className="module-summary-grid">
        <Card><div className="module-stat"><span>وضعیت اتصال</span><strong>{STATUS_LABEL[module.integration_level] || "در حال بررسی"}</strong></div></Card>
        <Card><div className="module-stat"><span>وضعیت گواهی</span><strong>{CERT_LABEL[module.certification_state] || "در حال بررسی"}</strong></div></Card>
        <Card><div className="module-stat"><span>قابلیت‌های AI</span><strong>{module.capability_count}</strong></div></Card>
      </div>

      {!operational && (
        <Alert>
          این برنامه نصب و شناسایی شده است؛ اما عملیات حساس آن تا زمان بررسی adapter و اجرای تست واقعی، از طریق AI فعال نمی‌شود.
        </Alert>
      )}

      <Card title="منوی برنامه">
        <MenuTree menus={module.menus || []} moduleId={moduleId} />
      </Card>
      <Card title="AI Workspace">
        <p className="muted">
          AI فقط بر اساس دسترسی کاربر و قابلیت‌های ثبت‌شده با این برنامه کار می‌کند. عملیات مالی، حذف، تأیید و سایر تغییرات حساس ممکن است نیازمند تأیید انسانی باشند.
        </p>
        <NavLink className="primary-btn" to="/chat">بازکردن AI Workspace</NavLink>
      </Card>
    </div>
  );
}
