import { Check } from "lucide-react";

const roleLabels = { admin: "Admin", project_manager: "Project Manager", supervisor: "Supervisor" };
const moduleLabels = { execution: "Execution", communication: "Communication Hub", users: "Users", overview: "Overview", projects: "Projects", approvals: "Approvals", today: "Today", security: "Security" };

export function PermissionMatrix({ data, onToggle }) {
  return (
    <section className="permission-panel overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm [&>header]:flex [&>header]:items-center [&>header]:justify-between [&>header]:gap-4 [&>header]:border-b [&>header]:border-slate-100 [&>header]:pb-4 max-[720px]:[&>header]:grid [&_h3]:m-0 [&_h3]:font-serif [&_h3]:text-xl [&_p]:m-0 [&_p]:text-sm [&_p]:text-slate-500 [&>header>span]:flex [&>header>span]:items-center [&>header>span]:gap-2 [&>header>span]:text-xs [&>header>span]:font-bold [&>header>span]:text-emerald-700">
      <header>
        <div><h3>Predefined system-role visibility</h3><p>These roles exist for access control even when no user is currently assigned to them.</p></div>
        <span><Check /> Backend role restrictions remain active</span>
      </header>
      <div className="permission-matrix mt-4 min-w-[720px] overflow-x-auto">
        <div className="matrix-head grid grid-cols-[minmax(220px,1.5fr)_repeat(3,1fr)] items-center gap-3 border-b border-slate-200 px-4 py-3 text-xs uppercase tracking-wider text-slate-500"><strong>Module</strong>{Object.entries(roleLabels).map(([role, label]) => <strong key={role}>{label}</strong>)}</div>
        {data.modules.map(moduleKey => (
          <div className="matrix-row grid grid-cols-[minmax(220px,1.5fr)_repeat(3,1fr)] items-center gap-3 border-b border-slate-100 px-4 py-4 [&>div>strong]:block [&>div>small]:mt-1 [&>div>small]:block [&>div>small]:text-xs [&>div>small]:text-slate-500" key={moduleKey}>
            <div><strong>{moduleLabels[moduleKey] || moduleKey}</strong><small>{moduleKey === "communication" ? "Primary workspace - always enabled" : "Show this module in navigation"}</small></div>
            {Object.keys(roleLabels).map(role => {
              const permission = data.permissions.find(item => item.role === role && item.module_key === moduleKey);
              return <label className={`permission-switch flex cursor-pointer items-center justify-center gap-2 [&_input]:sr-only [&>span]:relative [&>span]:h-6 [&>span]:w-11 [&>span]:rounded-full [&>span]:bg-slate-300 [&>span]:transition [&>span]:after:absolute [&>span]:after:left-1 [&>span]:after:top-1 [&>span]:after:size-4 [&>span]:after:rounded-full [&>span]:after:bg-white [&>span]:after:transition [&.on>span]:bg-blue-700 [&.on>span]:after:translate-x-5 [&.locked]:cursor-not-allowed [&.locked]:opacity-60 [&>b]:text-xs ${permission?.can_view ? "on" : ""} ${permission?.locked ? "locked" : ""}`} key={role}><input type="checkbox" checked={Boolean(permission?.can_view)} disabled={permission?.locked} onChange={() => onToggle(role, moduleKey)} /><span /><b>{permission?.can_view ? "Visible" : "Hidden"}</b></label>;
            })}
          </div>
        ))}
      </div>
    </section>
  );
}
