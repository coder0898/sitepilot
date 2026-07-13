import { BarChart3, BriefcaseBusiness, CalendarCheck, CheckSquare, FolderKanban, LogOut, RefreshCw, Settings, ShieldCheck, UserRoundCog, UsersRound } from "lucide-react";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";

export function tabHelp(tab) {
  return ({
    execution: "Three-day project scheduler",
    overview: "Product summary",
    users: "Create and manage logins",
    projects: "Calendar and task control",
    communication: "Project contacts & quick actions",
    approvals: "Review submitted work",
    today: "Current and carried-forward tasks",
    security: "Application settings",
    permissions: "Control role access",
  })[tab] || "Workspace";
}

function navIcon(tab) {
  const icons = {
    execution: <CalendarCheck size={18} />,
    overview: <BarChart3 size={18} />,
    users: <UsersRound size={18} />,
    projects: <FolderKanban size={18} />,
    communication: <BriefcaseBusiness size={18} />,
    approvals: <CheckSquare size={18} />,
    today: <CalendarCheck size={18} />,
    security: <Settings size={18} />,
    permissions: <ShieldCheck size={18} />,
  };
  return icons[tab] || <UserRoundCog size={18} />;
}

export function AppLayout({ user, tabs, activeTab, onTabChange, onLogout, onRefresh, notice, onClearNotice, children }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="logo-mark">45</div><div><strong>SiteOps</strong><span>Execution Portal</span></div></div>
        <div className="identity"><span>{roles[user.role]}</span><strong>{user.name}</strong><button type="button" onClick={onLogout}><LogOut size={18} /> Logout</button></div>
        <nav>{tabs.map(([key, label]) => <button type="button" key={key} onClick={() => onTabChange(key)} className={activeTab === key ? "active" : ""}><span className="nav-icon">{navIcon(key)}</span><span><b>{label}</b><small>{tabHelp(key)}</small></span></button>)}</nav>
        <div className="sidebar-profile"><div className="avatar small">{initials(user.name)}</div><div><strong>{user.name}</strong><span>{user.email}</span></div></div>
      </aside>
      <main className={`workspace tab-${activeTab}`}>
        <header className="page-head"><div><p>45-day interior fit-out control</p><h1>{tabs.find(([key]) => key === activeTab)?.[1]}</h1><span>{tabHelp(activeTab)}</span></div><div className="head-actions"><span>{new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</span><button type="button" className="refresh-button" onClick={onRefresh}><RefreshCw size={18} /> Refresh</button><button type="button" onClick={onLogout}>Logout</button></div></header>
        <div className="mobile-tabs">{tabs.map(([key, label]) => <button type="button" key={key} onClick={() => onTabChange(key)} className={activeTab === key ? "active" : ""}>{label}</button>)}</div>
        {notice && <div className="notice" onClick={onClearNotice}>{notice}</div>}
        {children}
      </main>
    </div>
  );
}
