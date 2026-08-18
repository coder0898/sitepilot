import { Briefcase, Building2, ContactRound, HardHat, UserRound } from "lucide-react";
import { cn } from "../../../utils/cn";

export const GROUP_META = {
  project_manager: { label: "PMs", icon: UserRound, tone: "border-blue-200 bg-blue-50 text-blue-700" },
  site_supervisor: { label: "Supervisors", icon: HardHat, tone: "border-violet-200 bg-violet-50 text-violet-700" },
  internal_employee: { label: "Internal Employees", icon: Briefcase, tone: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  vendor: { label: "Vendors", icon: Building2, tone: "border-amber-200 bg-amber-50 text-amber-700" },
  vendor_contact: { label: "Vendor Contacts", icon: ContactRound, tone: "border-rose-200 bg-rose-50 text-rose-700" },
};
export const GROUP_ORDER = Object.keys(GROUP_META);

export function RecipientGroupSelector({ counts, selectedGroups, onToggleGroup, onToggleAll, loading }) {
  const allSelected = GROUP_ORDER.every(group => selectedGroups.has(group));
  const totalSelected = GROUP_ORDER.reduce((sum, group) => sum + (selectedGroups.has(group) ? (counts[group] || 0) : 0), 0);

  return <div className="grid gap-3">
    <label className="flex cursor-pointer items-center gap-2 text-sm font-bold text-slate-700">
      <input type="checkbox" checked={allSelected} onChange={() => onToggleAll(!allSelected)} className="size-4 rounded border-slate-300 text-blue-600 focus:ring-blue-600" />
      Select all groups
      <span className="text-xs font-semibold text-slate-400">({totalSelected} recipient{totalSelected === 1 ? "" : "s"} selected)</span>
    </label>

    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {GROUP_ORDER.map(group => {
        const meta = GROUP_META[group];
        const Icon = meta.icon;
        const active = selectedGroups.has(group);
        return <button key={group} type="button" onClick={() => onToggleGroup(group)} aria-pressed={active}
          className={cn("flex flex-col items-start gap-2 rounded-2xl border p-3 text-left transition",
            active ? meta.tone : "border-slate-200 bg-white text-slate-500 hover:border-slate-300")}>
          <span className="flex w-full items-center justify-between">
            <Icon size={18} />
            <input type="checkbox" checked={active} readOnly className="size-4 rounded border-slate-300 text-blue-600" />
          </span>
          <span className="text-xs font-black">{meta.label}</span>
          <span className="text-lg font-black leading-none">{loading ? "…" : (counts[group] ?? 0)}</span>
        </button>;
      })}
    </div>
  </div>;
}
