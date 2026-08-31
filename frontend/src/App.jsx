import React, { useEffect, useMemo, useState } from "react";
import { Routes, Route, NavLink, Navigate } from "react-router-dom";
import * as api from "./api/client.js";
import LoginPage from "./pages/LoginPage.jsx";
import LeavesPage from "./pages/LeavesPage.jsx";
import DocumentCenterPage from "./pages/DocumentCenterPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import ChatPage from "./pages/ChatPage.jsx";
import IntegrationsPage from "./pages/IntegrationsPage.jsx";

const NAV = [
  ["/", "خانه", "⌂"], ["/chat", "AI Workspace", "✦"], ["/tasks", "کارها", "✓"],
  ["/calendar", "تقویم", "◷"], ["/departments", "دپارتمان‌ها", "▦"], ["/documents", "اسناد", "▤"],
  ["/knowledge", "Knowledge", "◇"], ["/approvals", "تأییدها", "◆"], ["/agents", "Agents", "◈"],
  ["/notifications", "اعلان‌ها", "●"], ["/integrations", "اتصالات", "↔"],
];

function Shell({ user, onLogout }) {
  const [caps, setCaps] = useState([]);
  const [notifCount, setNotifCount] = useState(0);
  useEffect(() => { api.getMyCapabilities().then(x => setCaps(x.capabilities || x || [])).catch(() => {}); api.getNotifications().then(x => setNotifCount((x.notifications || []).filter(n => !n.is_read).length)).catch(() => {}); }, []);
  const capabilitySet = useMemo(() => new Set(caps.map(c => typeof c === "string" ? c : c.name)), [caps]);
  return <div className="product-shell">
    <aside className="product-sidebar">
      <div className="brand"><div className="brand-mark">✦</div><div><strong>Nova Enterprise</strong><span>AI Operating System</span></div></div>
      <div className="user-card"><div className="avatar">{(user.name || "U").slice(0,1)}</div><div><strong>{user.name}</strong><span>{user.company || "سازمان"}</span></div></div>
      <nav className="product-nav">{NAV.map(([to,label,icon]) => <NavLink key={to} to={to} end={to === "/"} className={({isActive}) => `nav-item ${isActive ? "active" : ""}`}><i>{icon}</i><span>{label}</span>{label === "اعلان‌ها" && notifCount > 0 && <b>{notifCount}</b>}</NavLink>)}</nav>
      <div className="sidebar-bottom"><NavLink to="/admin" className="nav-item"><i>⚙</i><span>مدیریت</span></NavLink><button className="nav-item logout" onClick={() => { api.logout().catch(()=>{}); onLogout(); }}><i>↪</i><span>خروج</span></button></div>
    </aside>
    <main className="product-main"><Routes>
      <Route path="/" element={<Dashboard user={user} />} />
      <Route path="/chat" element={<ChatPage user={user} />} />
      <Route path="/tasks" element={<TasksPage />} /><Route path="/calendar" element={<CalendarPage />} />
      <Route path="/departments" element={<DepartmentsPage />} /><Route path="/documents" element={<DocumentCenterPage user={user} />} />
      <Route path="/knowledge" element={<KnowledgePage />} /><Route path="/approvals" element={<ApprovalsPage />} />
      <Route path="/agents" element={<AgentsPage />} /><Route path="/notifications" element={<NotificationsPage />} />
      <Route path="/integrations" element={<IntegrationsPage />} /><Route path="/leaves" element={<LeavesPage />} />
      <Route path="/admin" element={capabilitySet.has("admin.console.read") ? <AdminPage /> : <AccessDenied />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes></main>
  </div>;
}

const Card = ({children, className=""}) => <section className={`x-card ${className}`}>{children}</section>;
const Pill = ({children, tone="neutral"}) => <span className={`pill pill-${tone}`}>{children}</span>;
function PageHead({eyebrow,title,subtitle,action}) { return <header className="page-head"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{action}</header>; }

function Dashboard({user}) { const [data,setData]=useState({}); useEffect(()=>{api.getWorkspace().then(setData).catch(()=>{})},[]); return <><PageHead eyebrow="CONTROL CENTER" title={`سلام ${user.name.split(" ")[0]} 👋`} subtitle="تمام عملیات سازمان، AI و اتوماسیون از یک فضای واحد مدیریت می‌شوند." action={<NavLink className="primary-btn" to="/chat">✦ شروع گفتگو</NavLink>} /><div className="hero-grid"><Card className="hero-card"><div className="hero-glow"/><Pill tone="success">AI Online</Pill><h2>دستیار سازمانی شما آماده است.</h2><p>درخواست را طبیعی بنویسید؛ سیستم هویت، نقش، دسترسی، ریسک و Workflow را قبل از اجرا بررسی می‌کند.</p><NavLink className="primary-btn" to="/chat">گفتگو با Agent من →</NavLink></Card><Card><div className="metric"><span>Role</span><strong>{data.department?.name || "سازمان"}</strong><small>Effective access</small></div><div className="metric"><span>AI</span><strong>Active</strong><small>Model Router ready</small></div><div className="metric"><span>Security</span><strong>Protected</strong><small>Policy + ACL + FGA</small></div></Card></div><div className="section-title">دسترسی سریع</div><div className="quick-grid">{[["/chat","AI Workspace","هر کاری را با زبان طبیعی انجام بده"],["/documents","Documents","فایل‌ها و Knowledge با ACL"],["/approvals","Approvals","تأییدهای در انتظار شما"],["/agents","Role Agents","Agent متناسب با نقش شما"]].map(x=><NavLink className="quick-card" to={x[0]} key={x[0]}><strong>{x[1]}</strong><span>{x[2]}</span><b>→</b></NavLink>)}</div></>; }

function TasksPage(){const [tasks,setTasks]=useState([]);const [name,setName]=useState("");const load=()=>api.getTasks().then(x=>setTasks(x.tasks||[])).catch(()=>{});useEffect(load,[]);return <><PageHead eyebrow="WORK MANAGEMENT" title="کارها" subtitle="Task، مسئول، موعد و اتوماسیون در یک جا." action={<button className="primary-btn" onClick={async()=>{if(!name)return;await api.createTask({name});setName("");load()}}>+ کار جدید</button>}/><Card><div className="inline-form"><input value={name} onChange={e=>setName(e.target.value)} placeholder="عنوان تسک را بنویسید…"/><button className="primary-btn" onClick={async()=>{if(!name)return;await api.createTask({name});setName("");load()}}>ایجاد</button></div></Card><Card><Table headers={["تسک","وضعیت","عملیات"]} rows={tasks.map(t=>[<strong key={t.id}>{t.name}</strong>,<Pill tone="info">{t.state||"Open"}</Pill>,<button className="ghost-btn">مشاهده</button>])}/></Card></>;}
function CalendarPage(){return <><PageHead eyebrow="TIME" title="تقویم سازمانی" subtitle="مرخصی، جلسات و تسک‌ها در یک نمای زمانی."/><Card className="calendar-card"><div className="calendar-head"><strong>August 2026</strong><span>امروز • 19</span></div><div className="calendar-grid">{Array.from({length:35},(_,i)=><div className={`day ${i===18?"today":""}`} key={i}>{(i%31)+1}{i===18&&<small>Today</small>}</div>)}</div></Card></>}
function DepartmentsPage(){const [items,setItems]=useState([]);useEffect(()=>{api.getDepartments().then(x=>setItems(x.departments||[])).catch(()=>{})},[]);return <><PageHead eyebrow="ORGANIZATION" title="دپارتمان‌ها" subtitle="هر دپارتمان می‌تواند Chat، Agent، فایل، Knowledge و Workflow خودش را داشته باشد."/><div className="dept-grid">{items.map(d=><Card key={d.id}><div className="dept-icon">▦</div><h3>{d.name}</h3><p>{d.member_count} عضو</p><div className="dept-links"><button>Chat</button><button>Agent</button><button>Documents</button></div></Card>)}{!items.length&&<Card><Empty text="دپارتمان قابل نمایش پیدا نشد."/></Card>}</div></>}
function KnowledgePage(){return <><PageHead eyebrow="KNOWLEDGE" title="Knowledge" subtitle="دانش سازمانی با همان ACL فایل‌ها؛ AI فقط چیزهایی را می‌بیند که کاربر مجاز است."/><Card><div className="knowledge-hero"><div><Pill tone="success">ACL Protected</Pill><h2>دانش قابل اعتماد سازمان</h2><p>فایل‌های شخصی، تیمی، دپارتمانی و شرکتی می‌توانند جداگانه وارد Knowledge شوند.</p></div><NavLink className="primary-btn" to="/documents">مدیریت فایل‌ها</NavLink></div></Card></>}
function ApprovalsPage(){const [items,setItems]=useState([]);useEffect(()=>{api.getApprovals().then(x=>setItems(x.approvals||[])).catch(()=>{})},[]);return <><PageHead eyebrow="CONTROL" title="تأییدها" subtitle="عملیات حساس قبل از اجرا، طبق Policy و Role بررسی می‌شوند."/><Card><Table headers={["درخواست","درخواست‌کننده","Risk","وضعیت"]} rows={items.map(a=>[a.name,a.requester,<Pill tone={a.risk>70?"danger":"warning"}>{a.risk||0}</Pill>,<Pill tone="info">{a.state||"Pending"}</Pill>])}/></Card></>}
function AgentsPage(){const [items,setItems]=useState([]);useEffect(()=>{api.getAgents().then(x=>setItems(x.agents||[])).catch(()=>{})},[]);return <><PageHead eyebrow="AI AGENTS" title="Agents" subtitle="Agent هر نقش، فقط در محدوده Capabilityهای همان کاربر عمل می‌کند."/><div className="agent-grid">{items.map(a=><Card key={a.id}><div className="agent-orb">✦</div><h3>{a.name}</h3><p>{a.description||"Role-aware enterprise agent"}</p><div><Pill>{a.tools} tools</Pill><Pill tone="success">Policy bound</Pill></div></Card>)}{!items.length&&<Card><Empty text="Agentی ثبت نشده است."/></Card>}</div></>}
function NotificationsPage(){const [items,setItems]=useState([]);useEffect(()=>{api.getNotifications().then(x=>setItems(x.notifications||[])).catch(()=>{})},[]);return <><PageHead eyebrow="INBOX" title="اعلان‌ها" subtitle="رویدادهای Task، Approval، Document، Security و AI."/><Card><div className="notification-list">{items.map(n=><div className="notification" key={n.id}><div className="notif-dot"/><div><strong>{n.subject||"اعلان جدید"}</strong><p>{String(n.body || "").replace(/<[^>]*>/g, "")}</p><small>{n.date}</small></div></div>)}{!items.length&&<Empty text="اعلان جدیدی ندارید."/>}</div></Card></>}
function AccessDenied(){return <Card><h2>دسترسی مجاز نیست</h2><p>این بخش فقط برای نقش‌های مجاز در دسترس است.</p></Card>}
function Empty({text}){return <div className="empty">{text}</div>}
function Table({headers,rows}){return <div className="table-wrap"><table><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{r.map((c,j)=><td key={j}>{c}</td>)}</tr>)}</tbody></table></div>}

export default function App(){const [user,setUser]=useState(null);const [loading,setLoading]=useState(true);useEffect(()=>{api.getMe().then(setUser).catch(()=>setUser(null)).finally(()=>setLoading(false))},[]);if(loading)return <div className="boot">✦</div>;if(!user)return <LoginPage onLoggedIn={setUser}/>;return <Shell user={user} onLogout={()=>setUser(null)}/>;}
