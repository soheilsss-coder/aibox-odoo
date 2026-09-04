import React, { useEffect, useState } from "react";
import { Routes, Route, NavLink, Navigate } from "react-router-dom";
import * as api from "./api/client.js";
import LoginPage from "./pages/LoginPage.jsx";
import LeavesPage from "./pages/LeavesPage.jsx";
import DocumentCenterPage from "./pages/DocumentCenterPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import ChatPage from "./pages/ChatPage.jsx";
import IntegrationsPage from "./pages/IntegrationsPage.jsx";
import ModuleWorkspacePage from "./pages/ModuleWorkspacePage.jsx";
import ModuleMenuPage from "./pages/ModuleMenuPage.jsx";

const NAV = [
  ["/", "خانه", "⌂"], ["/chat", "AI Workspace", "✦"], ["/tasks", "کارها", "✓"],
  ["/calendar", "تقویم", "◷"], ["/departments", "دپارتمان‌ها", "▦"], ["/documents", "اسناد", "▤"],
  ["/knowledge", "Knowledge", "◇"], ["/approvals", "تأییدها", "◆"], ["/agents", "Agents", "◈"],
  ["/notifications", "اعلان‌ها", "●"], ["/integrations", "اتصالات", "↔"],
];

function Shell({ user, onLogout }) {
  const [notifCount, setNotifCount] = useState(0);
  const [moduleNav, setModuleNav] = useState([]);
  const [shellError, setShellError] = useState("");
  const loadModuleNav = () => api.getModuleNavigation()
    .then(x => setModuleNav(x.modules || []))
    .catch(e => setShellError(e instanceof api.ApiError ? e.message : "خطا در بارگذاری برنامه‌ها"));
  useEffect(() => {
    api.getNotifications()
      .then(x => setNotifCount((x.notifications || []).filter(n => !n.is_read).length))
      .catch(e => setShellError(e instanceof api.ApiError ? e.message : "خطا در بارگذاری اعلان‌ها"));
    loadModuleNav();
    const refresh = () => loadModuleNav();
    window.addEventListener("modules:changed", refresh);
    return () => window.removeEventListener("modules:changed", refresh);
  }, []);
  const canOpenAdmin = Boolean(user.is_admin);
  return <div className="product-shell">
    <aside className="product-sidebar">
      <div className="brand"><div className="brand-mark">✦</div><div><strong>Nova Enterprise</strong><span>AI Operating System</span></div></div>
      <div className="user-card"><div className="avatar">{(user.name || "U").slice(0,1)}</div><div><strong>{user.name}</strong><span>{user.company || "سازمان"}</span></div></div>
      <nav className="product-nav">{NAV.map(([to,label,icon]) => <NavLink key={to} to={to} end={to === "/"} className={({isActive}) => `nav-item ${isActive ? "active" : ""}`}><i>{icon}</i><span>{label}</span>{label === "اعلان‌ها" && notifCount > 0 && <b>{notifCount}</b>}</NavLink>)}{moduleNav.length > 0 && <div className="module-nav-group"><div className="module-nav-title">برنامه‌های سازمانی</div>{moduleNav.map(module => <NavLink key={module.id} to={`/modules/${module.id}`} className={({isActive}) => `nav-item module-nav-item ${isActive ? "active" : ""}`}><i>▣</i><span>{module.label}</span></NavLink>)}</div>}</nav>
      <div className="sidebar-bottom"><NavLink to="/admin" className="nav-item"><i>⚙</i><span>مدیریت</span></NavLink><button className="nav-item logout" onClick={() => { api.logout().catch(()=>{}); onLogout(); }}><i>↪</i><span>خروج</span></button></div>
    </aside>
    <main className="product-main">
      {shellError && <div className="error-text" role="alert" aria-live="polite">{shellError}</div>}
      <Routes>
      <Route path="/" element={<Dashboard user={user} />} />
      <Route path="/chat" element={<ChatPage user={user} />} />
      <Route path="/tasks" element={<TasksPage />} /><Route path="/calendar" element={<CalendarPage />} />
      <Route path="/departments" element={<DepartmentsPage />} /><Route path="/documents" element={<DocumentCenterPage user={user} />} />
      <Route path="/knowledge" element={<KnowledgePage />} /><Route path="/approvals" element={<ApprovalsPage />} />
      <Route path="/agents" element={<AgentsPage />} /><Route path="/notifications" element={<NotificationsPage />} />
      <Route path="/integrations" element={<IntegrationsPage />} /><Route path="/modules/:moduleId/menus/:menuId" element={<ModuleMenuPage />} /><Route path="/modules/:moduleId" element={<ModuleWorkspacePage />} /><Route path="/leaves" element={<LeavesPage />} />
      <Route path="/admin" element={canOpenAdmin ? <AdminPage /> : <AccessDenied />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes></main>
  </div>;
}

const Card = ({children, className=""}) => <section className={`x-card ${className}`}>{children}</section>;
const Pill = ({children, tone="neutral"}) => <span className={`pill pill-${tone}`}>{children}</span>;
function PageHead({eyebrow,title,subtitle,action}) { return <header className="page-head"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{action}</header>; }

function Dashboard({user}) { const [data,setData]=useState({}); const [error,setError]=useState(""); useEffect(()=>{api.getWorkspace().then(setData).catch(e=>setError(e.message||"خطا در بارگذاری فضای کاری"))},[]); return <><PageHead eyebrow="CONTROL CENTER" title={`سلام ${user.name.split(" ")[0]} 👋`} subtitle="تمام عملیات سازمان، AI و اتوماسیون از یک فضای واحد مدیریت می‌شوند." action={<NavLink className="primary-btn" to="/chat">✦ شروع گفتگو</NavLink>} />{error&&<p className="error-text">{error}</p>}<div className="hero-grid"><Card className="hero-card"><div className="hero-glow"/><Pill tone="success">AI Online</Pill><h2>دستیار سازمانی شما آماده است.</h2><p>درخواست را طبیعی بنویسید؛ سیستم هویت، نقش، دسترسی، ریسک و Workflow را قبل از اجرا بررسی می‌کند.</p><NavLink className="primary-btn" to="/chat">گفتگو با Agent من →</NavLink></Card><Card><div className="metric"><span>Role</span><strong>{data.department?.name || "سازمان"}</strong><small>Effective access</small></div><div className="metric"><span>AI</span><strong>Active</strong><small>Model Router ready</small></div><div className="metric"><span>Security</span><strong>Protected</strong><small>Policy + ACL + FGA</small></div></Card></div><div className="section-title">دسترسی سریع</div><div className="quick-grid">{[["/chat","AI Workspace","هر کاری را با زبان طبیعی انجام بده"],["/documents","Documents","فایل‌ها و Knowledge با ACL"],["/approvals","Approvals","تأییدهای در انتظار شما"],["/agents","Role Agents","Agent متناسب با نقش شما"]].map(x=><NavLink className="quick-card" to={x[0]} key={x[0]}><strong>{x[1]}</strong><span>{x[2]}</span><b>→</b></NavLink>)}</div></>; }

function TasksPage(){const [tasks,setTasks]=useState([]);const [name,setName]=useState("");const [error,setError]=useState("");const load=()=>api.getTasks().then(x=>setTasks(x.tasks||[])).catch(e=>setError(e.message||"خطا در بارگذاری کارها"));useEffect(load,[]);const create=async()=>{if(!name)return;setError("");try{await api.createTask({name});setName("");load();}catch(e){setError(e.message||"کار ایجاد نشد");}};return <><PageHead eyebrow="WORK MANAGEMENT" title="کارها" subtitle="Task، مسئول، موعد و اتوماسیون در یک جا." action={<button className="primary-btn" onClick={create}>+ کار جدید</button>}/>{error&&<p className="error-text">{error}</p>}<Card><div className="inline-form"><input value={name} onChange={e=>setName(e.target.value)} placeholder="عنوان تسک را بنویسید…"/><button className="primary-btn" onClick={create}>ایجاد</button></div></Card><Card><Table headers={["تسک","وضعیت","عملیات"]} rows={tasks.map(t=>[<strong key={t.id}>{t.name}</strong>,<Pill tone="info">{t.state||"Open"}</Pill>,<button className="ghost-btn" key={`view-${t.id}`}>مشاهده</button>])}/></Card></>;}
function CalendarPage(){
  const [events,setEvents]=useState([]); const [loading,setLoading]=useState(true); const [error,setError]=useState(""); const [name,setName]=useState(""); const [start,setStart]=useState(""); const [stop,setStop]=useState(""); const [saving,setSaving]=useState(false);
  const load=()=>{setLoading(true);setError("");api.getCalendar().then(x=>setEvents(x.events||[])).catch(e=>setError(e.message||"خطا در بارگذاری تقویم")).finally(()=>setLoading(false));};
  useEffect(load,[]);
  const create=async(e)=>{e.preventDefault();if(!name||!start)return;setSaving(true);setError("");const normalize=v=>v?v.replace("T"," ")+((v.length===16)?":00":""):v;try{await api.createCalendarEvent({name,start:normalize(start),stop:normalize(stop||start)});setName("");setStart("");setStop("");load();}catch(err){setError(err.message||"رویداد ایجاد نشد");}finally{setSaving(false);}};
  return <><PageHead eyebrow="TIME" title="تقویم سازمانی" subtitle="جلسه، مرخصی و مهلت کارها از داده‌های واقعی حساب شما نمایش داده می‌شوند."/><Card><form className="inline-form" onSubmit={create}><input value={name} onChange={e=>setName(e.target.value)} placeholder="عنوان رویداد"/><input type="datetime-local" value={start} onChange={e=>setStart(e.target.value)} required/><input type="datetime-local" value={stop} onChange={e=>setStop(e.target.value)}/><button className="primary-btn" disabled={saving}>{saving?"در حال ثبت…":"افزودن"}</button></form>{error&&<p className="error-text">{error}</p>}</Card><Card className="calendar-card">{loading?<p className="muted">در حال بارگذاری…</p>:events.length===0?<p className="muted">رویدادی برای نمایش وجود ندارد.</p>:<div className="event-list">{events.map(event=><div className="notification" key={event.id}><div className="notif-dot"/><div><strong>{event.name}</strong><p>{event.start||""}{event.stop?` تا ${event.stop}`:""}</p>{event.location&&<small>{event.location}</small>}</div></div>)}</div>}</Card></>}
function DepartmentsPage(){const [items,setItems]=useState([]);const [error,setError]=useState("");useEffect(()=>{api.getDepartments().then(x=>setItems(x.departments||[])).catch(e=>setError(e.message||"خطا در بارگذاری دپارتمان‌ها"))},[]);return <><PageHead eyebrow="ORGANIZATION" title="دپارتمان‌ها" subtitle="هر دپارتمان می‌تواند Chat، Agent، فایل، Knowledge و Workflow خودش را داشته باشد."/>{error&&<p className="error-text">{error}</p>}<div className="dept-grid">{items.map(d=><Card key={d.id}><div className="dept-icon">▦</div><h3>{d.name}</h3><p>{d.member_count} عضو</p><div className="dept-links"><button>Chat</button><button>Agent</button><button>Documents</button></div></Card>)}{!items.length&&!error&&<Card><Empty text="دپارتمان قابل نمایش پیدا نشد."/></Card>}</div></>}
function KnowledgePage(){return <><PageHead eyebrow="KNOWLEDGE" title="Knowledge" subtitle="دانش سازمانی با همان ACL فایل‌ها؛ AI فقط چیزهایی را می‌بیند که کاربر مجاز است."/><Card><div className="knowledge-hero"><div><Pill tone="success">ACL Protected</Pill><h2>دانش قابل اعتماد سازمان</h2><p>فایل‌های شخصی، تیمی، دپارتمانی و شرکتی می‌توانند جداگانه وارد Knowledge شوند.</p></div><NavLink className="primary-btn" to="/documents">مدیریت فایل‌ها</NavLink></div></Card></>}
function ApprovalsPage(){
  const [items,setItems]=useState([]); const [loading,setLoading]=useState(true); const [error,setError]=useState(""); const [busy,setBusy]=useState(null);
  const load=()=>{setLoading(true);setError("");api.getApprovals().then(x=>setItems(x.approvals||[])).catch(e=>setError(e.message||"خطا در بارگذاری تأییدها")).finally(()=>setLoading(false));};
  useEffect(load,[]);
  const decide=async(a,kind)=>{setBusy(a.id);setError("");try{if(kind==="approve")await api.approveApproval(a.id);else await api.rejectApproval(a.id);load();}catch(e){setError(e.message||"عملیات انجام نشد");}finally{setBusy(null);}};
  return <><PageHead eyebrow="CONTROL" title="تأییدها" subtitle="عملیات حساس قبل از اجرا، طبق Policy و Role بررسی می‌شوند."/><Card>{error&&<p className="error-text">{error}</p>}{loading?<p className="muted">در حال بارگذاری…</p>:!items.length?<p className="muted">تأیید در انتظاری وجود ندارد.</p>:<Table headers={["درخواست","درخواست‌کننده","ریسک","وضعیت","عملیات"]} rows={items.map(a=>[a.name,a.requested_by,<Pill tone={(a.risk_level||0)>=3?"danger":"warning"}>{a.risk_level??"—"}</Pill>,<Pill tone={a.state==="approved"?"success":a.state==="rejected"?"danger":"info"}>{a.state||"Pending"}</Pill>,a.can_decide&&a.state==="pending"?<span><button className="ghost-btn" disabled={busy===a.id} onClick={()=>decide(a,"approve")}>تأیید</button><button className="ghost-btn" disabled={busy===a.id} onClick={()=>decide(a,"reject")}>رد</button></span>:<span className="muted">—</span>])}/>}</Card></>}
function AgentsPage(){const [items,setItems]=useState([]);const [error,setError]=useState("");useEffect(()=>{api.getAgents().then(x=>setItems(x.agents||[])).catch(e=>setError(e.message||"خطا در بارگذاری دستیارها"))},[]);return <><PageHead eyebrow="AI WORKSPACE" title="دستیار شخصی شما" subtitle="همان دستیار سازمانی با حافظه شخصی و دسترسی‌های مؤثر شما؛ هسته اصلی برای همه مشترک است."/>{error&&<p className="error-text">{error}</p>}<div className="agent-grid">{items.map(a=><Card key={a.id}><div className="agent-orb">✦</div><h3>{a.name}</h3><p>{a.description||"دستیار سازمانی متناسب با نقش شما"}</p><div><Pill>{a.tools || 0} ابزار مجاز</Pill><Pill>{a.connected_module_count || 0} برنامه متصل</Pill><Pill tone={a.connection_state === "connected" ? "success" : "warning"}>{a.connection_state === "connected" ? "متصل" : "در حال بررسی"}</Pill></div><p className="muted" style={{marginTop:12}}>نقش کاری: {a.role || "سازمان"} · {a.memory_scope || "حافظه شخصی"}</p><Pill tone="info">هسته مشترک، پروفایل شخصی</Pill></Card>)}{!items.length&&!error&&<Card><Empty text="دستیار شخصی هنوز آماده نشده است."/></Card>}</div></>}
function NotificationsPage(){const [items,setItems]=useState([]);const [error,setError]=useState("");useEffect(()=>{api.getNotifications().then(x=>setItems(x.notifications||[])).catch(e=>setError(e.message||"خطا در بارگذاری اعلان‌ها"))},[]);return <><PageHead eyebrow="INBOX" title="اعلان‌ها" subtitle="رویدادهای Task، Approval، Document، Security و AI."/>{error&&<p className="error-text">{error}</p>}<Card><div className="notification-list">{items.map(n=><div className="notification" key={n.id}><div className="notif-dot"/><div><strong>{n.subject||"اعلان جدید"}</strong><p>{String(n.body || "").replace(/<[^>]*>/g, "")}</p><small>{n.date}</small></div></div>)}{!items.length&&!error&&<Empty text="اعلان جدیدی ندارید."/>}</div></Card></>}
function AccessDenied(){return <Card><h2>دسترسی مجاز نیست</h2><p>این بخش فقط برای نقش‌های مجاز در دسترس است.</p></Card>}
function Empty({text}){return <div className="empty">{text}</div>}
function Table({headers,rows}){return <div className="table-wrap"><table><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{r.map((c,j)=><td key={j}>{c}</td>)}</tr>)}</tbody></table></div>}

export default function App(){const [user,setUser]=useState(null);const [loading,setLoading]=useState(true);useEffect(()=>{api.getMe().then(setUser).catch(()=>setUser(null)).finally(()=>setLoading(false))},[]);if(loading)return <div className="boot">✦</div>;if(!user)return <LoginPage onLoggedIn={setUser}/>;return <Shell user={user} onLogout={()=>setUser(null)}/>;}
