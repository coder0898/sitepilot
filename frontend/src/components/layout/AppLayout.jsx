import { LogOut, MoreHorizontal, RefreshCw, UserRoundCog } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";
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

// Beyond this many items, an equal-width single row squeezes every label
// down to 2-3 letters ("Pro...", "Por...") on a real phone - the crowded
// bottom nav a wide-permission role (Admin/Super Admin, up to 7 tabs) hits.
// Standard mobile nav guidance caps a bottom bar at 5 slots; past that, the
// last slot becomes "More" instead of a 6th/7th squeezed button.
const MAX_VISIBLE_MOBILE_TABS = 5;

function MobileTabButton({ tab, label, active, onClick }) {
  return <button type="button" onClick={onClick} aria-current={active ? "page" : undefined} className={`grid min-h-[58px] min-w-0 place-items-center content-center gap-1 rounded-2xl px-1 text-[10px] font-black transition ${active ? "bg-slate-950 text-white shadow-lg" : "text-slate-500 hover:bg-slate-100 hover:text-slate-950"}`}>
    <TabIcon tab={tab} size={20}/><span className="max-w-full truncate">{label}</span>
  </button>;
}

function MoreTabsSheet({ tabs, activeTab, onSelect, onClose }) {
  return createPortal(
    <div className="fixed inset-0 z-40 bg-slate-950/40 lg:hidden" role="presentation" onClick={onClose}>
      <div
        role="menu"
        aria-label="More navigation"
        className="fixed inset-x-2 bottom-[calc(6rem+env(safe-area-inset-bottom))] z-50 grid gap-1 rounded-[22px] border border-slate-200/80 bg-white p-2 shadow-[0_18px_55px_rgba(15,23,42,.25)]"
        onClick={event => event.stopPropagation()}
      >
        {tabs.map(([key, label]) => {
          const active = activeTab === key;
          return <button type="button" key={key} role="menuitem" onClick={() => onSelect(key)} aria-current={active ? "page" : undefined} className={`flex min-h-14 min-w-0 items-center gap-3 rounded-2xl px-3 text-left transition ${active ? "bg-slate-950 text-white" : "text-slate-700 hover:bg-slate-100"}`}>
            <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${active ? "bg-white/10" : "bg-slate-100"}`}><TabIcon tab={key} size={19}/></span>
            <span className="min-w-0"><b className="block truncate text-sm">{label}</b><small className={`mt-0.5 block truncate text-[11px] ${active ? "text-slate-300" : "text-slate-400"}`}>{tabHelp(key)}</small></span>
          </button>;
        })}
      </div>
    </div>,
    document.body,
  );
}

function MobileNavigation({ tabs, activeTab, onTabChange }) {
  const [showMore, setShowMore] = useState(false);
  const hasOverflow = tabs.length > MAX_VISIBLE_MOBILE_TABS;
  const primaryTabs = hasOverflow ? tabs.slice(0, MAX_VISIBLE_MOBILE_TABS - 1) : tabs;
  const overflowTabs = hasOverflow ? tabs.slice(MAX_VISIBLE_MOBILE_TABS - 1) : [];
  const overflowActive = overflowTabs.some(([key]) => key === activeTab);

  function selectOverflowTab(key) {
    setShowMore(false);
    onTabChange(key);
  }

  return <>
    <nav aria-label="Mobile navigation" className="fixed inset-x-2 bottom-2 z-40 grid grid-flow-col auto-cols-fr gap-1 rounded-[22px] border border-slate-200/80 bg-white/95 p-1.5 pb-[max(.375rem,env(safe-area-inset-bottom))] shadow-[0_18px_55px_rgba(15,23,42,.2)] backdrop-blur-xl lg:hidden">
      {primaryTabs.map(([key, label]) => <MobileTabButton key={key} tab={key} label={label.replace("Vendor Hub", "Vendors").replace("Role Permissions", "Roles")} active={activeTab === key} onClick={() => onTabChange(key)}/>)}
      {hasOverflow && <button type="button" onClick={() => setShowMore(true)} aria-haspopup="true" aria-expanded={showMore} className={`grid min-h-[58px] min-w-0 place-items-center content-center gap-1 rounded-2xl px-1 text-[10px] font-black transition ${overflowActive ? "bg-slate-950 text-white shadow-lg" : "text-slate-500 hover:bg-slate-100 hover:text-slate-950"}`}>
        <MoreHorizontal aria-hidden="true" size={20}/><span>More</span>
      </button>}
    </nav>
    {hasOverflow && showMore && <MoreTabsSheet tabs={overflowTabs} activeTab={activeTab} onSelect={selectOverflowTab} onClose={() => setShowMore(false)}/>}
  </>;
}

function SidebarIconButton({ label, onClick, children }) {
  return <IconButton variant="ghost" className="!text-slate-300 hover:!bg-white/10 hover:!text-white" aria-label={label} onClick={onClick}>{children}</IconButton>;
}

export function AppLayout({ user, tabs, activeTab, onTabChange, onLogout, onRefresh, notice, onClearNotice, children }) {
  const activeLabel = tabs.find(([key]) => key === activeTab)?.[1] || "Workspace";
  return <div className="min-h-dvh min-w-0 bg-[radial-gradient(circle_at_10%_0%,rgba(219,234,254,.9),transparent_28%),linear-gradient(145deg,#f8fafc_0%,#eef4fb_56%,#f8fafc_100%)] text-slate-950 lg:grid lg:grid-cols-[272px_minmax(0,1fr)]">
    <aside className="sticky top-0 hidden h-dvh min-w-0 min-h-0 flex-col gap-5 overflow-hidden bg-[#071a33] p-5 text-white lg:flex">
      <div className="flex shrink-0 items-center gap-3 px-1"><div className="grid size-12 place-items-center rounded-2xl bg-blue-600 text-xl font-black shadow-[0_14px_30px_rgba(37,99,235,.3)]">45</div><div><strong className="block text-xl tracking-tight">SiteOps</strong><span className="text-xs font-medium text-blue-200">Execution intelligence</span></div></div>
      <div className="flex shrink-0 items-center gap-3 rounded-2xl border border-white/10 bg-white/[.06] p-4"><div className="min-w-0 flex-1"><span className="text-xs font-semibold text-blue-200">{roles[user.role]}</span><strong className="mt-1 block truncate text-sm">{user.name}</strong></div><SidebarIconButton label="Refresh workspace" onClick={onRefresh}><RefreshCw size={18}/></SidebarIconButton></div>
      <DesktopNav tabs={tabs} activeTab={activeTab} onTabChange={onTabChange}/>
      <div className="shrink-0 border-t border-white/10 pt-4"><div className="flex min-w-0 items-center gap-3"><div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-blue-600 font-black">{initials(user.name)}</div><div className="min-w-0 flex-1"><strong className="block truncate text-sm">{user.name}</strong><span className="block truncate text-xs text-slate-400">{user.email}</span></div><SidebarIconButton label="Logout" onClick={onLogout}><LogOut size={18}/></SidebarIconButton></div></div>
    </aside>

    <div className="min-w-0">
      <header className="sticky top-0 z-30 flex min-h-[70px] items-center gap-3 border-b border-slate-200/80 bg-white/90 px-4 backdrop-blur-xl lg:hidden"><div className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-600 font-black text-white">45</div><div className="min-w-0 flex-1"><span className="block text-[10px] font-black uppercase tracking-[.18em] text-blue-700">SiteOps</span><strong className="block truncate text-base">{activeLabel}</strong></div><IconButton variant="secondary" aria-label="Refresh workspace" onClick={onRefresh}><RefreshCw size={18}/></IconButton><IconButton variant="ghost" aria-label="Logout" onClick={onLogout}><LogOut size={18}/></IconButton></header>
      <main className={`min-w-0 max-w-full overflow-x-hidden px-3 pb-28 pt-3 sm:px-5 sm:pt-5 lg:p-8 lg:pb-8 tab-${activeTab}`}>
        {notice && <Alert className="mb-4" onDismiss={onClearNotice}>{notice}</Alert>}
        {children}
      </main>
    </div>
    <MobileNavigation tabs={tabs} activeTab={activeTab} onTabChange={onTabChange}/>
  </div>;
}