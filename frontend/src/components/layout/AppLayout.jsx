import { LogOut, RefreshCw, UserRoundCog } from "lucide-react";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";
import { getTabDefinition } from "../../config/tabs";
import { Alert, IconButton } from "../ui";

export function tabHelp(tab) {
  return getTabDefinition(tab)?.help || "Workspace";
}

function TabIcon({ tab, size = 19 }) {
  const Icon = getTabDefinition(tab)?.icon || UserRoundCog;
  return <Icon aria-hidden="true" size={size} />;
}

function DesktopNav({ tabs, activeTab, onTabChange }) {
  return <nav aria-label="Primary navigation" className="grid min-h-0 flex-1 content-start gap-1.5 overflow-x-hidden overflow-y-auto pr-1">
    {tabs.map(([key, label]) => {
      const active = activeTab === key;
      return <button type="button" key={key} onClick={() => onTabChange(key)} aria-current={active ? "page" : undefined} className={`group flex min-h-14 min-w-0 max-w-full items-center gap-3 rounded-2xl px-3 text-left transition ${active ? "bg-blue-600 text-white shadow-[0_16px_35px_rgba(37,99,235,.28)]" : "text-slate-300 hover:bg-white/10 hover:text-white"}`}>
        <span className={`grid size-10 shrink-0 place-items-center rounded-xl border ${active ? "border-white/20 bg-white/10" : "border-white/10 bg-white/5 group-hover:border-white/20"}`}><TabIcon tab={key}/></span>
        <span className="min-w-0"><b className="block truncate text-sm">{label}</b><small className={`mt-0.5 block truncate text-[11px] ${active ? "text-blue-100" : "text-slate-400"}`}>{tabHelp(key)}</small></span>
      </button>;
    })}
  </nav>;
}

function MobileNavigation({ tabs, activeTab, onTabChange }) {
  return <nav aria-label="Mobile navigation" className="fixed inset-x-2 bottom-2 z-40 grid grid-flow-col auto-cols-fr gap-1 rounded-[22px] border border-slate-200/80 bg-white/95 p-1.5 pb-[max(.375rem,env(safe-area-inset-bottom))] shadow-[0_18px_55px_rgba(15,23,42,.2)] backdrop-blur-xl lg:hidden">
    {tabs.map(([key, label]) => {
      const active = activeTab === key;
      return <button type="button" key={key} onClick={() => onTabChange(key)} aria-current={active ? "page" : undefined} className={`grid min-h-[58px] min-w-0 place-items-center content-center gap-1 rounded-2xl px-1 text-[10px] font-black transition ${active ? "bg-slate-950 text-white shadow-lg" : "text-slate-500 hover:bg-slate-100 hover:text-slate-950"}`}>
        <TabIcon tab={key} size={20}/><span className="max-w-full truncate">{label.replace("Communication Hub", "Contacts").replace("Role Permissions", "Roles")}</span>
      </button>;
    })}
  </nav>;
}

export function AppLayout({ user, tabs, activeTab, onTabChange, onLogout, onRefresh, notice, onClearNotice, children }) {
  const activeLabel = tabs.find(([key]) => key === activeTab)?.[1] || "Workspace";
  return <div className="min-h-dvh min-w-0 bg-[radial-gradient(circle_at_10%_0%,rgba(219,234,254,.9),transparent_28%),linear-gradient(145deg,#f8fafc_0%,#eef4fb_56%,#f8fafc_100%)] text-slate-950 lg:grid lg:grid-cols-[272px_minmax(0,1fr)]">
    <aside className="sticky top-0 hidden h-dvh min-w-0 min-h-0 flex-col gap-5 overflow-hidden bg-[#071a33] p-5 text-white lg:flex">
      <div className="flex shrink-0 items-center gap-3 px-1"><div className="grid size-12 place-items-center rounded-2xl bg-blue-600 text-xl font-black shadow-[0_14px_30px_rgba(37,99,235,.3)]">45</div><div><strong className="block text-xl tracking-tight">SiteOps</strong><span className="text-xs font-medium text-blue-200">Execution intelligence</span></div></div>
      <div className="shrink-0 rounded-2xl border border-white/10 bg-white/[.06] p-4"><span className="text-xs font-semibold text-blue-200">{roles[user.role]}</span><strong className="mt-1 block truncate text-sm">{user.name}</strong></div>
      <DesktopNav tabs={tabs} activeTab={activeTab} onTabChange={onTabChange}/>
      <div className="shrink-0 border-t border-white/10 pt-4"><div className="flex min-w-0 items-center gap-3"><div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-blue-600 font-black">{initials(user.name)}</div><div className="min-w-0 flex-1"><strong className="block truncate text-sm">{user.name}</strong><span className="block truncate text-xs text-slate-400">{user.email}</span></div><IconButton variant="ghost" className="!text-slate-300 hover:!bg-white/10 hover:!text-white" aria-label="Logout" onClick={onLogout}><LogOut size={18}/></IconButton></div></div>
    </aside>

    <div className="min-w-0">
      <header className="sticky top-0 z-30 flex min-h-[70px] items-center gap-3 border-b border-slate-200/80 bg-white/90 px-4 backdrop-blur-xl lg:hidden"><div className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-600 font-black text-white">45</div><div className="min-w-0 flex-1"><span className="block text-[10px] font-black uppercase tracking-[.18em] text-blue-700">SiteOps</span><strong className="block truncate text-base">{activeLabel}</strong></div><IconButton variant="secondary" aria-label="Refresh workspace" onClick={onRefresh}><RefreshCw size={18}/></IconButton><IconButton variant="ghost" aria-label="Logout" onClick={onLogout}><LogOut size={18}/></IconButton></header>
      <main className={`min-w-0 max-w-full overflow-x-hidden px-3 pb-28 pt-3 sm:px-5 sm:pt-5 lg:p-8 lg:pb-8 tab-${activeTab}`}>
        <header className="mb-6 hidden items-end justify-between gap-6 rounded-[28px] border border-white/80 bg-white/85 px-7 py-6 shadow-[0_22px_70px_rgba(15,45,86,.08)] backdrop-blur lg:flex"><div><p className="text-[10px] font-black uppercase tracking-[.22em] text-blue-700">45-day interior fit-out control</p><h1 className="mt-2 text-[clamp(36px,4vw,58px)] font-black tracking-[-.055em] text-slate-950">{activeLabel}</h1><span className="mt-1 block text-sm text-slate-500">{tabHelp(activeTab)}</span></div><div className="flex items-center gap-2"><span className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-black text-slate-600">{new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</span><IconButton variant="secondary" aria-label="Refresh workspace" onClick={onRefresh}><RefreshCw size={18}/></IconButton></div></header>
        {notice && <Alert className="mb-4" onDismiss={onClearNotice}>{notice}</Alert>}
        {children}
      </main>
    </div>
    <MobileNavigation tabs={tabs} activeTab={activeTab} onTabChange={onTabChange}/>
  </div>;
}