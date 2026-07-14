import { LogOut, UserRoundCog } from "lucide-react";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";
import { getTabDefinition } from "../../config/tabs";
import { Alert, RefreshButton } from "../ui";

export function tabHelp(tab) {
  return getTabDefinition(tab)?.help || "Workspace";
}

function navIcon(tab) {
  const Icon = getTabDefinition(tab)?.icon;
  return Icon ? <Icon size={18} /> : <UserRoundCog size={18} />;
}

export function AppLayout({ user, tabs, activeTab, onTabChange, onLogout, onRefresh, notice, onClearNotice, children }) {
  return (
    <div className="app-shell grid min-h-screen min-w-0 grid-cols-[280px_minmax(0,1fr)] max-[920px]:block">
      <aside className="sidebar sticky top-0 flex h-screen flex-col gap-5 overflow-hidden bg-gradient-to-b from-[#071831] to-[#0a1e3b] p-6 text-white max-[920px]:static max-[920px]:h-auto max-[920px]:rounded-b-[28px] max-[920px]:bg-white max-[920px]:text-slate-950 max-[920px]:shadow-sm [&_nav]:grid [&_nav]:gap-2 max-[920px]:[&_nav]:hidden [&_nav_button]:flex [&_nav_button]:w-full [&_nav_button]:items-center [&_nav_button]:gap-3 [&_nav_button]:rounded-xl [&_nav_button]:bg-transparent [&_nav_button]:px-4 [&_nav_button]:py-4 [&_nav_button]:text-left [&_nav_button]:font-bold [&_nav_button]:text-white [&_nav_button]:shadow-none [&_nav_button.active]:bg-gradient-to-br [&_nav_button.active]:from-blue-600 [&_nav_button.active]:to-blue-500 [&_nav_button.active]:shadow-[0_18px_40px_rgba(11,91,211,0.35)] [&_nav_small]:mt-1 [&_nav_small]:block [&_nav_small]:font-medium [&_nav_small]:text-blue-200">
        <div className="brand shrink-0 flex items-center gap-4 [&_strong]:block [&_strong]:text-[22px] [&_span]:text-blue-200"><div className="logo-mark grid size-[54px] shrink-0 place-items-center rounded-[18px] bg-blue-700 text-[21px] font-black text-white shadow-[0_16px_30px_rgba(11,91,211,0.25)]">45</div><div><strong>SiteOps</strong><span>Execution Portal</span></div></div>
        <div className="identity shrink-0 grid gap-2 rounded-2xl border border-white/15 bg-white/5 p-4 max-[920px]:grid-cols-[1fr_auto] max-[920px]:items-center max-[920px]:border-slate-200 max-[920px]:bg-slate-50 [&>span]:text-blue-200 max-[920px]:[&>span]:text-slate-500 [&>button]:mt-2 [&>button]:flex [&>button]:items-center [&>button]:justify-center [&>button]:gap-2 [&>button]:rounded-xl [&>button]:bg-white [&>button]:px-4 [&>button]:py-3 [&>button]:font-black [&>button]:text-blue-800 max-[920px]:[&>button]:mt-0 max-[920px]:[&>button]:bg-blue-700 max-[920px]:[&>button]:text-white"><span>{roles[user.role]}</span><strong>{user.name}</strong><button type="button" onClick={onLogout}><LogOut size={18} /> Logout</button></div>
        <nav className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1 [scrollbar-gutter:stable]">{tabs.map(([key, label]) => <button type="button" key={key} onClick={() => onTabChange(key)} className={activeTab === key ? "active" : ""}><span className="nav-icon grid size-9 shrink-0 place-items-center rounded-xl border border-white/20">{navIcon(key)}</span><span><b>{label}</b><small>{tabHelp(key)}</small></span></button>)}</nav>
        <div className="sidebar-profile shrink-0 flex min-w-0 items-center gap-3 border-t border-white/10 pt-4 max-[920px]:hidden [&>div:last-child]:min-w-0 [&_strong]:block [&_span]:block [&_span]:truncate [&_span]:text-xs [&_span]:text-blue-200"><div className="avatar grid size-[46px] shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-blue-900 font-black text-white shadow-[0_12px_24px_rgba(11,91,211,0.22)] small">{initials(user.name)}</div><div><strong>{user.name}</strong><span>{user.email}</span></div></div>
      </aside>
      <main className={`workspace min-w-0 max-w-full overflow-x-hidden p-7 max-[920px]:p-5 max-[520px]:p-3 tab-${activeTab}`}>
        <header className="page-head mb-5 flex items-center justify-between gap-6 rounded-[26px] border border-blue-100 bg-white/90 px-7 py-6 shadow-[0_22px_60px_rgba(15,45,86,0.08)] max-[920px]:block [&_p]:m-0 [&_p]:text-xs [&_p]:font-black [&_p]:uppercase [&_p]:tracking-[0.18em] [&_p]:text-slate-500 [&_h1]:m-0 [&_h1]:text-[clamp(34px,6vw,58px)] [&_h1]:font-black [&_h1]:tracking-[-0.07em] [&>div>span]:text-slate-500"><div><p>45-day interior fit-out control</p><h1>{tabs.find(([key]) => key === activeTab)?.[1]}</h1><span>{tabHelp(activeTab)}</span></div><div className="head-actions flex items-center gap-3 max-[920px]:hidden [&>span]:rounded-2xl [&>span]:border [&>span]:border-slate-200 [&>span]:bg-white [&>span]:px-4 [&>span]:py-3 [&>span]:font-black [&>button]:min-h-11 [&>button]:rounded-xl [&>button]:px-4 [&>button]:font-black"><span>{new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</span><RefreshButton className="refresh-button" onClick={onRefresh}>Refresh</RefreshButton></div></header>
        <div className="mobile-tabs mb-5 hidden gap-2 overflow-x-auto rounded-2xl border border-slate-200 bg-white p-2 max-[920px]:flex [&>button]:min-w-[140px] [&>button]:rounded-xl [&>button]:bg-transparent [&>button]:px-4 [&>button]:py-3 [&>button]:font-black [&>button]:text-slate-900 [&>button.active]:bg-blue-700 [&>button.active]:text-white">{tabs.map(([key, label]) => <button type="button" key={key} onClick={() => onTabChange(key)} className={activeTab === key ? "active" : ""}>{label}</button>)}</div>
        {notice && <Alert className="notice mb-4" onDismiss={onClearNotice}>{notice}</Alert>}
        {children}
      </main>
    </div>
  );
}
