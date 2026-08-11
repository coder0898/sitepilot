import { Search } from "lucide-react";
import { useMemo } from "react";
import { Pill } from "../../../components/ui";
import { relativeAge } from "../../../utils/format";

const statusTone = { draft: "gray", active: "green", on_hold: "orange", completed: "blue", archived: "gray" };
const statusLabel = value => value.replace("_", " ");

// "All" deliberately excludes archived: an archived project is closed
// business, and letting it accumulate in the default-widest filter makes
// that filter useless within a year. The Archived chip only appears when
// there is something archived to look at.
const BASE_FILTERS = [["active", "Active"], ["draft", "Draft"], ["on_hold", "On hold"], ["completed", "Completed"], ["all", "All"]];

export function filterProjects(projects, filter) {
  if (filter === "all") return projects.filter(item => item.status !== "archived");
  return projects.filter(item => item.status === filter);
}

function setupCount(project) {
  return [
    project.setup?.has_project_manager,
    project.setup?.has_site_supervisor,
    project.setup?.has_template,
    project.setup?.has_target_handover_date,
  ].filter(Boolean).length;
}

function Meter({ project, summary }) {
  if (project.status === "draft") {
    const ready = setupCount(project);
    return <div className="mt-2 flex items-center gap-2">
      <span className="h-1 flex-1 overflow-hidden rounded-full bg-slate-100"><span className="block h-full rounded-full bg-amber-500" style={{ width: `${ready * 25}%` }}/></span>
      <span className="shrink-0 text-[10px] font-black tabular-nums text-slate-500">{ready}/4</span>
    </div>;
  }
  // No summary endpoint yet - render nothing rather than a permanently
  // empty progress bar that reads as "0% done".
  if (!summary || typeof summary.progress_pct !== "number") return null;
  return <div className="mt-2 flex items-center gap-2">
    <span className="h-1 flex-1 overflow-hidden rounded-full bg-slate-100"><span className="block h-full rounded-full bg-blue-600" style={{ width: `${summary.progress_pct}%` }}/></span>
    <span className="shrink-0 text-[10px] font-black tabular-nums text-slate-500">{summary.progress_pct}%</span>
  </div>;
}

function ProjectRow({ project, summary, attentionCount, active, onOpen }) {
  const age = relativeAge(summary?.last_activity_at);
  return <button
    type="button"
    onClick={() => onOpen(project)}
    aria-current={active ? "true" : undefined}
    className={`relative block w-full border-b border-slate-100 px-3 py-2.5 text-left transition ${active ? "bg-blue-50 before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-blue-600" : "hover:bg-slate-50"}`}
  >
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <span className="block truncate font-mono text-[10px] text-slate-400">{project.code}</span>
        <strong className="mt-0.5 block truncate text-sm text-slate-950">{project.name}</strong>
        <span className="block truncate text-xs text-slate-500">{project.client_name}</span>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {attentionCount > 0 && <span className="rounded bg-rose-50 px-1.5 py-px font-mono text-[10px] font-black text-rose-700">{attentionCount}</span>}
        <Pill tone={statusTone[project.status]}>{statusLabel(project.status)}</Pill>
      </div>
    </div>
    <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-slate-400">
      <span className="truncate">{project.memberships?.find(item => item.project_role === "project_manager")?.name || "No PM"}</span>
      {age && <span className="ml-auto shrink-0">{age}</span>}
    </div>
    <Meter project={project} summary={summary}/>
  </button>;
}

export function ProjectListPane({ projects, summaries, attentionByProject, filter, onFilterChange, search, onSearchChange, selectedId, onOpen }) {
  const hasArchived = projects.some(item => item.status === "archived");
  const filters = hasArchived ? [...BASE_FILTERS, ["archived", "Archived"]] : BASE_FILTERS;

  const counts = useMemo(() => Object.fromEntries(
    filters.map(([key]) => [key, filterProjects(projects, key).length])
  ), [projects, hasArchived]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return filterProjects(projects, filter).filter(project => !term || [project.code, project.name, project.client_name, project.site_address]
      .some(value => String(value || "").toLowerCase().includes(term)));
  }, [projects, filter, search]);

  return <div className="flex min-h-0 min-w-0 flex-col border-slate-200 bg-white lg:border-r">
    <div className="grid gap-2 border-b border-slate-200 p-3">
      <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1.5 focus-within:border-blue-600 focus-within:ring-4 focus-within:ring-blue-600/10">
        <Search size={15} className="shrink-0 text-slate-400" aria-hidden="true"/>
        <input
          value={search}
          onChange={event => onSearchChange(event.target.value)}
          placeholder="Search name, code, client or site"
          aria-label="Search projects"
          className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-slate-400"
        />
      </label>
      <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
        {filters.map(([key, label]) => <button
          key={key}
          type="button"
          onClick={() => onFilterChange(key)}
          aria-pressed={filter === key}
          className={`rounded-full border px-2 py-0.5 text-[11px] font-bold transition ${filter === key ? "border-blue-600 bg-blue-600 text-white" : "border-slate-200 bg-slate-50 text-slate-600 hover:text-slate-950"}`}
        >{label}<span className="ml-1 font-mono opacity-70">{counts[key]}</span></button>)}
      </div>
    </div>

    {/* Stacked on mobile the list would otherwise push the workspace off
        screen, so cap it there and let it fill the column on desktop. */}
    <div className="max-h-72 min-h-0 flex-1 overflow-y-auto lg:max-h-none">
      {visible.length
        ? visible.map(project => <ProjectRow
            key={project.id}
            project={project}
            summary={summaries?.[project.id]}
            attentionCount={attentionByProject?.[project.id] || 0}
            active={selectedId === project.id}
            onOpen={onOpen}
          />)
        : <p className="px-4 py-10 text-center text-xs text-slate-400">{search.trim() ? "No projects match this search." : "No projects in this filter."}</p>}
    </div>
  </div>;
}
