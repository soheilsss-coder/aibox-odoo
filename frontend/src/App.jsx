import React, { useEffect, useMemo, useState } from "react";
import { Routes, Route, NavLink, Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import * as api from "./api/client.js";
import { Icon, IconButton } from "./components";
import { useThreads, relDate, removeThread } from "./hooks/useThreads.js";
import LoginPage from "./pages/LoginPage.jsx";
import ChatPage from "./pages/ChatPage.jsx";
import TasksPage from "./pages/TasksPage.jsx";
import ApprovalsPage from "./pages/ApprovalsPage.jsx";
import LeavesPage from "./pages/LeavesPage.jsx";
import CalendarPage from "./pages/CalendarPage.jsx";
import DepartmentsPage from "./pages/DepartmentsPage.jsx";
import DocumentCenterPage from "./pages/DocumentCenterPage.jsx";
import KnowledgePage from "./pages/KnowledgePage.jsx";
import AgentsPage from "./pages/AgentsPage.jsx";
import NotificationsPage from "./pages/NotificationsPage.jsx";
import IntegrationsPage from "./pages/IntegrationsPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";

const NAV = [
  {
    section: null,
    items: [{ to: "/", label: "AI Chat", icon: "spark", end: true }],
  },
  {
    section: "Work",
    items: [
      { to: "/tasks", label: "Tasks", icon: "tasks" },
      { to: "/approvals", label: "Approvals", icon: "shield" },
      { to: "/leaves", label: "Leave", icon: "clock" },
      { to: "/calendar", label: "Calendar", icon: "calendar" },
    ],
  },
  {
    section: "Organization",
    items: [
      { to: "/departments", label: "Departments", icon: "building" },
      { to: "/documents", label: "Documents", icon: "file" },
      { to: "/knowledge", label: "Knowledge", icon: "database" },
      { to: "/agents", label: "Agents", icon: "bot" },
    ],
  },
  {
    section: "System",
    items: [
      { to: "/integrations", label: "Integrations", icon: "plug" },
      { to: "/notifications", label: "Notifications", icon: "bell", badge: true },
    ],
  },
];

function useTheme() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || "light");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("nova.theme", theme); } catch { /* ignore */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "light" ? "dark" : "light"))];
}

function Brand() {
  return (
    <Link to="/" className="brand" aria-label="Nova home">
      <span className="orb" style={{ width: 34, height: 34 }} />
      <span>
        <span className="brand-name">Nova Enterprise</span>
        <span className="brand-sub" style={{ display: "block" }}>AI Operating System</span>
      </span>
    </Link>
  );
}

// Dedicated conversations menu — the chat page's own panel. It lives NEXT TO
// the app navigation (Tasks, Approvals, ...) as a separate column, like the
// history rail in ChatGPT/Claude: New chat + the user's conversation list.
function ChatPanel({ threads, activeId, open, onClose, onNavigateThread }) {
  const navigate = useNavigate();
  return (
    <aside className={`chat-panel ${open ? "open" : "closed"}`} aria-label="Chat conversations">
      <div className="chat-panel-head">
        <span className="chat-panel-title">Chats</span>
        <IconButton icon="chevronsLeft" label="Collapse chats panel" className="panel-collapse-btn" onClick={onClose} />
      </div>
      <Link to="/" className="btn btn-primary btn-block new-chat-btn" onClick={onNavigateThread}>
        <Icon name="plus" size={16} /> New chat
      </Link>
      <div className="threads" aria-label="Recent chats">
        {threads.length > 0 && <div className="nav-sec chat-panel-sec">Recent chats</div>}
        <div className="threads-scroll">
          {threads.map((t) => (
            <Link
              key={t.id}
              to={`/chat/${t.id}`}
              className={`thread-row ${activeId === t.id ? "active" : ""}`}
              title={t.title || "New chat"}
              onClick={onNavigateThread}
            >
              <Icon name="message" size={15} />
              <span className="thread-title">{t.title || "New chat"}</span>
              <span className="thread-date">{relDate(t.updatedAt)}</span>
              <button
                className="thread-del"
                aria-label={`Delete chat ${t.title || ""}`}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  removeThread(t.id);
                  if (activeId === t.id) navigate("/");
                }}
              >
                <Icon name="trash" size={13} />
              </button>
            </Link>
          ))}
        </div>
      </div>
    </aside>
  );
}

function Shell({ user, onLogout }) {
  const [caps, setCaps] = useState([]);
  const [adminFlag, setAdminFlag] = useState(false);
  const [notifCount, setNotifCount] = useState(0);
  const [navOpen, setNavOpen] = useState(false);
  const [theme, toggleTheme] = useTheme();
  const location = useLocation();
  const threads = useThreads();
  const activeThreadId = location.pathname.startsWith("/chat/") ? location.pathname.slice(6) : null;
  const isChatRoute = location.pathname === "/" || location.pathname.startsWith("/chat/");
  // The conversations panel is open by default; preference persists.
  const [chatsOpen, setChatsOpen] = useState(() => {
    try { return localStorage.getItem("nova.chatsPanel") !== "0"; } catch { return true; }
  });
  useEffect(() => {
    try { localStorage.setItem("nova.chatsPanel", chatsOpen ? "1" : "0"); } catch { /* ignore */ }
  }, [chatsOpen]);
  const closePanelOnMobile = () => {
    try { if (window.matchMedia("(max-width: 960px)").matches) setChatsOpen(false); } catch { /* ignore */ }
  };

  useEffect(() => {
    api.getMyCapabilities()
      .then((x) => {
        setCaps(x.capabilities || x || []);
        setAdminFlag(Boolean(x.is_admin));
      })
      .catch(() => {});
    api.getNotifications()
      .then((x) => setNotifCount((x.notifications || []).filter((n) => !n.is_read).length))
      .catch(() => {});
  }, []);

  // Close the mobile drawer on every navigation.
  useEffect(() => { setNavOpen(false); }, [location.pathname]);

  const capabilitySet = useMemo(
    () => new Set(caps.map((c) => (typeof c === "string" ? c : c.name))),
    [caps]
  );
  const isAdmin = capabilitySet.has("admin.console.read") || adminFlag;

  const items = useMemo(() => {
    const sections = NAV.map((s) => ({ ...s, items: [...s.items] }));
    if (isAdmin) {
      sections.push({
        section: "Administration",
        items: [{ to: "/admin", label: "Admin Console", icon: "cog" }],
      });
    }
    return sections;
  }, [isAdmin]);

  return (
    <div className="shell">
      <div className="topbar">
        <IconButton icon="menu" label="Open menu" onClick={() => setNavOpen(true)} />
        <span className="orb" style={{ width: 26, height: 26 }} />
        <strong className="brand-name" style={{ fontSize: 15 }}>Nova Enterprise</strong>
      </div>

      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}

      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <Brand />

        <nav className="nav" aria-label="Primary">
          {items.map((section) => (
            <React.Fragment key={section.section ?? "home"}>
              {section.section && <div className="nav-sec">{section.section}</div>}
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                >
                  <Icon name={item.icon} size={18} />
                  <span>{item.label}</span>
                  {item.badge && notifCount > 0 && <span className="nav-badge">{notifCount}</span>}
                </NavLink>
              ))}
            </React.Fragment>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="user-card">
            <div className="avatar">{(user.name || "U").slice(0, 1).toUpperCase()}</div>
            <div className="who">
              <strong>{user.name}</strong>
              <span>{user.company || "Organization"}</span>
            </div>
          </div>
          <div className="h-stack" style={{ padding: "2px 4px 0" }}>
            <IconButton
              icon={theme === "light" ? "moon" : "sun"}
              label={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
              onClick={toggleTheme}
            />
            <span className="grow" />
            <IconButton
              icon="logout"
              label="Log out"
              onClick={() => { api.logout().catch(() => {}); onLogout(); }}
            />
          </div>
        </div>
      </aside>

      {/* Conversations menu — the chat page's own panel, separate from the
          app navigation. Desktop: a fixed second column; mobile: a drawer. */}
      {isChatRoute && (
        <>
          <ChatPanel
            threads={threads}
            activeId={activeThreadId}
            open={chatsOpen}
            onClose={() => setChatsOpen(false)}
            onNavigateThread={closePanelOnMobile}
          />
          {chatsOpen && <div className="scrim panel-scrim" onClick={() => setChatsOpen(false)} />}
        </>
      )}

      <main className="main">
        <div className="route-enter" key={location.pathname}>
          <Routes location={location}>
            <Route path="/" element={<ChatPage user={user} chatsOpen={chatsOpen} onOpenChats={() => setChatsOpen(true)} />} />
            <Route path="/chat/:id" element={<ChatPage user={user} chatsOpen={chatsOpen} onOpenChats={() => setChatsOpen(true)} />} />
            <Route path="/chat" element={<Navigate to="/" replace />} />
            <Route path="/tasks" element={<div className="page"><TasksPage /></div>} />
            <Route path="/approvals" element={<div className="page"><ApprovalsPage /></div>} />
            <Route path="/leaves" element={<div className="page"><LeavesPage /></div>} />
            <Route path="/calendar" element={<div className="page"><CalendarPage /></div>} />
            <Route path="/departments" element={<div className="page"><DepartmentsPage /></div>} />
            <Route path="/documents" element={<div className="page"><DocumentCenterPage user={user} /></div>} />
            <Route path="/knowledge" element={<div className="page"><KnowledgePage /></div>} />
            <Route path="/agents" element={<div className="page"><AgentsPage /></div>} />
            <Route path="/notifications" element={<div className="page"><NotificationsPage /></div>} />
            <Route path="/integrations" element={<div className="page"><IntegrationsPage /></div>} />
            <Route
              path="/admin"
              element={
                isAdmin ? <div className="page"><AdminPage /></div> : <div className="page"><AccessDenied /></div>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

function AccessDenied() {
  return (
    <div className="card" style={{ textAlign: "center", padding: 48 }}>
      <div className="empty-icon" style={{ margin: "0 auto 12px" }}>
        <Icon name="shield" size={24} />
      </div>
      <h2 style={{ fontSize: 20 }}>Access restricted</h2>
      <p className="muted" style={{ marginTop: 8 }}>This area is only available to privileged roles.</p>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getMe().then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="boot">
        <span className="orb" />
      </div>
    );
  }
  if (!user) return <LoginPage onLoggedIn={setUser} />;
  return <Shell user={user} onLogout={() => setUser(null)} />;
}
