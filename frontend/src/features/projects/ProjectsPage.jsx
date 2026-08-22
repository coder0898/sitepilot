import { FolderKanban, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { projectsApi } from "../../api/projectsApi";
import { Button, EmptyState, LoadingSpinner, RefreshButton } from "../../components/ui";
import { useRoute } from "../../lib/route";
import { AttentionMenu } from "./components/AttentionMenu";
import { ProjectFormModal } from "./components/ProjectFormModal";
import { filterProjects, ProjectListPane } from "./components/ProjectListPane";
import { ProjectWorkspace } from "./components/ProjectWorkspace";

const CAN_CREATE = ["admin", "super_admin"];

function readApiError(error) {
  const detail = error?.details?.detail;
  if (Array.isArray(detail)) {
    return detail.map(item => {
      const location = Array.isArray(item.loc) ? item.loc.filter(part => part !== "body").join(".") : "";
      return `${location ? `${location}: ` : ""}${item.msg || "Invalid value"}`;
    }).join(" ");
  }
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return error?.message || "Unable to save project.";
}

export function ProjectsPage({ user, action }) {
  const [projects, setProjects] = useState([]);
  const [references, setReferences] = useState({ project_managers: [], supervisors: [], internal_employees: [] });
  const [publishedTemplates, setPublishedTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templatesError, setTemplatesError] = useState("");
  // Additive read models. Null means "not available", which is different
  // from an empty list and is what every consumer checks before rendering
  // progress, phases or the attention counter.
  const [summaries, setSummaries] = useState(null);
  const [attention, setAttention] = useState(null);

  const [route, setRoute] = useRoute();
  const [filter, setFilter] = useState("active");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [formProject, setFormProject] = useState(undefined);
  const [formError, setFormError] = useState("");
  const initialLoadStarted = useRef(false);
  // `projects` state is not readable synchronously right after load() in the
  // same tick, so keep the last fetched list here for post-save lookups.
  const loadedProjects = useRef([]);
  // Bumped only by the manual Refresh button, never by refreshAll() on its
  // own (post-save calls already reload themselves in place) - folded into
  // ProjectWorkspace's key below so a manual refresh also forces the open
  // project's workspace and every pane inside it (dependencies, external
  // gates, vendors, template review) to re-fetch, not just the list.
  const [refreshNonce, setRefreshNonce] = useState(0);

  async function loadPublishedTemplates() {
    if (!CAN_CREATE.includes(user.role)) {
      setPublishedTemplates([]);
      return;
    }
    setTemplatesLoading(true);
    setTemplatesError("");
    try {
      const response = await projectsApi.publishedTemplates();
      const items = Array.isArray(response) ? response : (response?.items || []);
      setPublishedTemplates(items.filter(item => item.status === "published"));
    } catch (error) {
      setPublishedTemplates([]);
      setTemplatesError(error?.message || "Unable to load published templates. Refresh and try again.");
    } finally {
      setTemplatesLoading(false);
    }
  }

  async function load() {
    setLoading(true);
    try {
      const [items, refs] = await Promise.all([projectsApi.list(), projectsApi.references()]);
      setProjects(items);
      loadedProjects.current = items;
      setReferences({
        ...refs,
        project_managers: (refs.project_managers || []).filter(item => item.availability !== "unavailable"),
        supervisors: (refs.supervisors || []).filter(item => item.availability !== "unavailable"),
      });
      await loadPublishedTemplates();
    } catch (error) {
      await action(() => Promise.reject(error), "", { refresh: false });
    } finally {
      setLoading(false);
    }
    return loadedProjects.current;
  }

  // Deliberately not awaited alongside the required calls: neither endpoint
  // exists yet, and a 404 here must never stop the project list rendering.
  async function loadReadModels() {
    const [summaryRows, attentionRows] = await Promise.all([
      projectsApi.summaries().catch(() => null),
      projectsApi.attention().catch(() => null),
    ]);
    setSummaries(Array.isArray(summaryRows)
      ? Object.fromEntries(summaryRows.map(row => [row.project_id, row]))
      : null);
    setAttention(Array.isArray(attentionRows) ? attentionRows : null);
  }

  useEffect(() => {
    if (initialLoadStarted.current) return;
    initialLoadStarted.current = true;
    load();
    loadReadModels();
  }, []);

  const filtered = useMemo(() => filterProjects(projects, filter), [projects, filter]);
  const selected = useMemo(
    () => projects.find(item => item.code === route.project) || null,
    [projects, route.project],
  );

  // Open straight into a project rather than a dead "nothing selected"
  // pane. Replace, not push, so Back does not walk through auto-selections.
  useEffect(() => {
    if (loading || selected) return;
    const fallback = filtered[0] || projects.find(item => item.status !== "archived");
    if (fallback) setRoute({ project: fallback.code, pane: route.pane || "overview" }, { replace: true });
  }, [loading, selected, filtered, projects]);

  const attentionByProject = useMemo(() => {
    if (!attention) return {};
    return attention.reduce((totals, item) => ({ ...totals, [item.project_id]: (totals[item.project_id] || 0) + 1 }), {});
  }, [attention]);

  const selectedAttention = useMemo(
    () => (attention && selected ? attention.filter(item => item.project_id === selected.id) : []),
    [attention, selected],
  );

  function openProject(project) {
    setRoute({ project: project.code, pane: "overview" });
  }

  function openFromAttention(item) {
    const project = projects.find(candidate => candidate.id === item.project_id);
    if (!project) return;
    // Jumping to a project outside the current filter would select a row
    // that is not on screen - widen the filter so the selection stays visible.
    if (!filterProjects(projects, filter).some(candidate => candidate.id === project.id)) setFilter("all");
    setRoute({ project: project.code, pane: item.pane || "overview" });
  }

  async function refreshAll() {
    const items = await load();
    await loadReadModels();
    return items;
  }

  async function manualRefresh() {
    await refreshAll();
    setRefreshNonce(current => current + 1);
  }

  async function saveProject(payload) {
    if (saving) return;
    setSaving(true);
    setFormError("");
    const editing = Boolean(formProject);
    try {
      if (editing) {
        await projectsApi.update(formProject.id, payload);
        setFormProject(undefined);
        await refreshAll();
        setRoute({ project: formProject.code, pane: route.pane || "overview" });
      } else {
        const created = await projectsApi.create(payload);
        setFormProject(undefined);
        const items = await refreshAll();
        // POST returns the full project JSON, but resolve the code off the
        // refreshed list when possible so this does not silently stop
        // selecting the new project if that response shape ever narrows.
        const code = created?.code || items?.find(item => item.id === (created?.id || created?.project_id))?.code;
        if (code) setRoute({ project: code, pane: "overview" });
      }
    } catch (error) {
      setFormError(readApiError(error));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <section className="rounded-[28px] border border-slate-200/80 bg-white p-6"><LoadingSpinner label="Loading project portfolio…"/></section>;
  }

  return <section className="grid min-w-0 gap-4">
    <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200/80 bg-white px-4 py-3">
      <div className="min-w-0">
        <h2 className="text-base font-black tracking-tight text-slate-950">Projects</h2>
        <p className="text-xs text-slate-500">Manage your projects and execution lifecycle</p>
      </div>
      <div className="flex items-center gap-2">
        <RefreshButton onClick={manualRefresh} loading={loading}/>
        <AttentionMenu items={attention} onOpen={openFromAttention}/>
        {CAN_CREATE.includes(user.role) && <Button onClick={() => { setFormError(""); setFormProject(null); }}>
          <Plus size={17}/> New project
        </Button>}
      </div>
    </header>

    {projects.length === 0
      ? <EmptyState
          icon={<FolderKanban size={21}/>}
          title="Create the first controlled project"
          description={CAN_CREATE.includes(user.role)
            ? "Start with a draft, assign accountability, then attach the approved 45-day template."
            : "Projects will appear when you receive an active project membership."}
          action={CAN_CREATE.includes(user.role) && formProject === undefined
            ? <Button onClick={() => { setFormError(""); setFormProject(null); }}><Plus size={17}/> Create draft</Button>
            : null}
        />
      : <div className="grid min-h-[34rem] min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white lg:grid-cols-[minmax(0,19rem)_minmax(0,1fr)]">
          <ProjectListPane
            projects={projects}
            summaries={summaries}
            attentionByProject={attentionByProject}
            filter={filter}
            onFilterChange={setFilter}
            search={search}
            onSearchChange={setSearch}
            selectedId={selected?.id}
            onOpen={openProject}
          />
          <div className="min-w-0 bg-slate-50/60">
            {selected
              ? <ProjectWorkspace
                  key={`${selected.id}:${refreshNonce}`}
                  projectId={selected.id}
                  references={references}
                  templates={publishedTemplates}
                  user={user}
                  summary={summaries?.[selected.id]}
                  attention={selectedAttention}
                  pane={route.pane || "overview"}
                  onPaneChange={next => setRoute({ pane: next })}
                  onEdit={project => { setFormError(""); setFormProject(project); }}
                  onChanged={refreshAll}
                  onDeleted={async () => { setRoute({ project: "", pane: "" }, { replace: true }); await refreshAll(); }}
                />
              : <p className="p-10 text-center text-sm text-slate-400">Select a project from the list.</p>}
          </div>
        </div>}

    {formProject !== undefined && <ProjectFormModal
      project={formProject}
      references={references}
      templates={publishedTemplates}
      templatesLoading={templatesLoading}
      templatesError={templatesError}
      apiError={formError}
      onClose={() => { if (!saving) setFormProject(undefined); }}
      onSubmit={saveProject}
      saving={saving}
    />}
  </section>;
}
