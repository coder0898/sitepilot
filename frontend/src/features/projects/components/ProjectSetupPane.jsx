import { Check, CircleAlert, Clock3 } from "lucide-react";
import { useEffect, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Alert, Button, Pill } from "../../../components/ui";

const longDate = value => (value
  ? new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
  : "Not set");

function ReadinessRow({ label, ready, detail }) {
  return <div className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm ${ready ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-slate-200 bg-white text-slate-500"}`}>
    {ready ? <Check size={16} className="mt-0.5 shrink-0"/> : <Clock3 size={16} className="mt-0.5 shrink-0"/>}
    <span className="min-w-0">
      <strong className="block font-bold">{label}</strong>
      {detail && <span className="block text-xs opacity-80">{detail}</span>}
    </span>
  </div>;
}

export function ProjectSetupPane({ project, activity, templates = [], user, onChanged, onOpenPane }) {
  const isAdmin = ["admin", "super_admin"].includes(user.role);
  const generationEvent = activity.find(event => event.action === "PROJECT_TASKS_GENERATED");
  const createdEvent = activity.find(event => event.action === "PROJECT_CREATED");
  const generatedCount = generationEvent?.after?.generated_task_count
    || createdEvent?.after?.generated_task_count
    || 0;
  const selectedTemplate = templates.find(item => item.version_id === project.template_version_id);

  const [counts, setCounts] = useState({ dependencies: null, gates: null });
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([
      projectsApi.dependencies(project.id).catch(() => null),
      projectsApi.externalGates(project.id).catch(() => null),
    ]).then(([dependencies, gates]) => {
      if (!active) return;
      setCounts({ dependencies: dependencies?.total ?? null, gates: gates?.total ?? null });
    });
    return () => { active = false; };
  }, [project.id, generatedCount]);

  async function run(kind) {
    setBusy(kind);
    setError("");
    try {
      if (kind === "tasks") await projectsApi.generateTasks(project.id);
      if (kind === "dependencies") await projectsApi.generateDependencies(project.id);
      if (kind === "gates") await projectsApi.generateGates(project.id);
      setConfirmed(false);
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "That step could not be completed. Review the project and retry.");
    } finally {
      setBusy("");
    }
  }

  const hasTasks = generatedCount > 0;
  const setup = project.setup || {};
  const readyCount = [setup.has_project_manager, setup.has_site_supervisor, setup.has_template, setup.has_target_handover_date].filter(Boolean).length;
  const activationReady = setup.activation_ready && hasTasks;

  return <div className="grid gap-3">
    {error && <Alert tone="danger">{error}</Alert>}

    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-black text-slate-950">{activationReady ? "Ready to activate" : "Setup incomplete"}</h3>
          <p className="mt-0.5 text-xs text-slate-500">
            The schedule is prepared automatically when a project is created. This project stays Draft until an Admin activates it.
          </p>
        </div>
        <Pill tone={activationReady ? "green" : "orange"}>{readyCount}/4 activation details</Pill>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <ReadinessRow label="Project Manager" ready={setup.has_project_manager} detail={project.memberships?.find(item => item.project_role === "project_manager")?.name}/>
        <ReadinessRow label="Site Supervisor" ready={setup.has_site_supervisor} detail={project.memberships?.find(item => item.project_role === "site_supervisor")?.name}/>
        <ReadinessRow label="Approved template" ready={setup.has_template} detail={selectedTemplate?.template_name}/>
        <ReadinessRow label="Target handover" ready={setup.has_target_handover_date} detail={longDate(project.target_handover_date)}/>
        <ReadinessRow
          label="Task schedule"
          ready={hasTasks}
          detail={hasTasks ? `${generatedCount} tasks prepared` : "No tasks prepared yet"}
        />
        <ReadinessRow
          label="Dependencies and approvals"
          ready={(counts.dependencies ?? 0) > 0 || (counts.gates ?? 0) > 0}
          detail={counts.dependencies === null ? "Checking…" : `${counts.dependencies} dependencies, ${counts.gates ?? 0} approval gates`}
        />
      </div>

      <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
        <Button variant="secondary" onClick={() => onOpenPane("template-review")}>Review tasks</Button>
        <Button variant="secondary" onClick={() => onOpenPane("dependencies")}>Review dependencies</Button>
        <Button variant="secondary" onClick={() => onOpenPane("external-gates")}>Review approvals</Button>
        <Button className="sm:ml-auto" disabled={!activationReady} onClick={() => onOpenPane("lifecycle")}>
          {activationReady ? "Go to activation" : "Activation blocked"}
        </Button>
      </div>
    </section>

    {/* Only reachable for drafts created before setup became automatic, or if
        generation was rolled back. New projects never see this. */}
    {!hasTasks && <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 sm:p-5">
      <div className="flex items-start gap-2">
        <CircleAlert size={16} className="mt-0.5 shrink-0 text-amber-700"/>
        <div className="min-w-0">
          <h3 className="text-sm font-black text-amber-900">This draft has no task schedule</h3>
          <p className="mt-1 text-xs leading-5 text-amber-800">
            It was created before the schedule was prepared automatically. Activation needs at least one included
            task, so prepare it here.
          </p>
        </div>
      </div>

      {isAdmin ? <div className="mt-3 grid gap-2">
        <div className="grid gap-1 rounded-xl border border-amber-200 bg-white p-3 text-xs">
          <strong className="text-slate-900">{selectedTemplate?.template_name || "Attached published template"}</strong>
          <span className="text-slate-500">
            {selectedTemplate ? `${selectedTemplate.template_code} · Version ${selectedTemplate.version_no} · ${selectedTemplate.duration_days} days` : "Published reference"}
          </span>
        </div>
        <label className="flex cursor-pointer items-start gap-2 rounded-xl border border-amber-200 bg-white p-2.5 text-xs text-slate-700">
          <input type="checkbox" checked={confirmed} disabled={Boolean(busy)} onChange={event => setConfirmed(event.target.checked)} className="mt-0.5 size-4"/>
          <span>I confirm the selected published template is correct. The project stays Draft.</span>
        </label>
        <div>
          <Button className="w-full sm:w-auto" loading={busy === "tasks"} disabled={!confirmed || Boolean(busy)} onClick={() => run("tasks")}>
            {error ? "Retry generation" : "Generate tasks"}
          </Button>
        </div>
      </div> : <p className="mt-2 text-xs font-bold text-amber-800">Only Admin can prepare the task schedule.</p>}
    </section>}

    {hasTasks && isAdmin && ((counts.dependencies === 0) || (counts.gates === 0)) && <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-black text-slate-950">Finish preparing this draft</h3>
      <p className="mt-1 text-xs text-slate-500">
        {counts.dependencies === 0 ? "Dependencies" : "Approval gates"} were not prepared for this project. Activation
        does not require them, but the schedule is incomplete without them.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {counts.dependencies === 0 && <Button loading={busy === "dependencies"} disabled={Boolean(busy)} onClick={() => run("dependencies")}>Generate dependencies</Button>}
        {counts.gates === 0 && <Button variant="secondary" loading={busy === "gates"} disabled={Boolean(busy)} onClick={() => run("gates")}>Generate approval gates</Button>}
      </div>
    </section>}

    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <h3 className="text-sm font-black text-slate-950">Captured at creation</h3>
      <dl className="mt-3 grid gap-3 sm:grid-cols-4">
        {[
          ["Project Manager", project.memberships?.find(item => item.project_role === "project_manager")?.name || "Not assigned"],
          ["Supervisor", project.memberships?.find(item => item.project_role === "site_supervisor")?.name || "Not assigned"],
          ["Start", longDate(project.start_date)],
          ["Handover", longDate(project.target_handover_date)],
        ].map(([label, value]) => <div key={label}>
          <dt className="font-mono text-[10px] uppercase tracking-[.1em] text-slate-400">{label}</dt>
          <dd className="mt-0.5 truncate text-sm font-semibold text-slate-900">{value}</dd>
        </div>)}
      </dl>
    </section>
  </div>;
}
