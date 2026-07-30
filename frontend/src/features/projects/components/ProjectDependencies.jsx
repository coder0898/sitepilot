import { AlertTriangle, Check, GitBranch, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, EmptyState, Pill } from "../../../components/ui";

const typeLabel = { finish_to_start: "Finish to Start", start_to_start: "Start to Start" };

export function ProjectDependencies({ project, user }) {
  const [data, setData] = useState({ total: 0, excluded_warning_count: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ predecessor_project_task_id: "", successor_project_task_id: "", dependency_type: "finish_to_start", reason: "" });
  const submitRef = useRef(false);
  const canGenerate = ["admin", "super_admin"].includes(user.role) && project.status === "draft";

  async function load() {
    setLoading(true); setError("");
    try { setData(await projectsApi.dependencies(project.id)); }
    catch (caught) { setError(caught?.message || "Unable to load project dependencies."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [project.id]);

  async function generate() {
    if (!canGenerate || !confirmed || busy || submitRef.current) return;
    submitRef.current = true; setBusy(true); setError("");
    try { await projectsApi.generateDependencies(project.id); setConfirmed(false); await load(); }
    catch (caught) { setError(caught?.message || "Unable to generate project dependencies."); }
    finally { submitRef.current = false; setBusy(false); }
  }

  return <div className="grid gap-4">
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-violet-50 text-violet-700"><GitBranch size={18}/></span><div><h3 className="font-black text-slate-950">Project dependencies</h3><p className="mt-1 text-xs leading-5 text-slate-500">Project-owned relationships remapped to generated project task IDs.</p></div></div><div className="flex gap-2"><Pill tone="blue">{data.total} dependencies</Pill>{data.excluded_warning_count > 0 && <Pill tone="orange">{data.excluded_warning_count} warnings</Pill>}</div></div>
    </section>
    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}<Button variant="secondary" className="ml-3" onClick={load}><RotateCcw size={15}/> Retry</Button></div>}
    {loading ? <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm font-bold text-slate-500">Loading dependencies...</div> : data.total === 0 ? <>
      <EmptyState icon={<GitBranch size={20}/>} title="No project dependencies generated" description="Generate dependencies after the complete project task snapshot exists."/>
      {canGenerate && <section className="rounded-2xl border border-blue-200 bg-blue-50/60 p-4 sm:p-5"><label className="flex items-start gap-3 rounded-xl border border-blue-200 bg-white p-3 text-sm text-slate-700"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} className="mt-0.5 size-4"/><span>I confirm project tasks are reviewed. Dependency generation remains Draft and does not activate work.</span></label><Button className="mt-4 w-full sm:w-auto" disabled={!confirmed || busy} loading={busy} onClick={generate}>Generate dependencies</Button></section>}
    </> : <div className="grid gap-3">{data.items.map(item => <article key={item.id} className={`rounded-2xl border bg-white p-4 sm:p-5 ${item.excluded_task_warning ? "border-amber-300" : "border-slate-200"}`}><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-black text-violet-700">#{item.sequence}</span><Pill tone="gray">{typeLabel[item.dependency_type]}</Pill>{item.blocking && <Pill tone="red">Blocking</Pill>}</div><h4 className="mt-2 font-black text-slate-950">{item.predecessor_code} → {item.successor_code}</h4><p className="mt-1 text-sm text-slate-600">{item.predecessor_title} → {item.successor_title}</p>{item.rule_text && <p className="mt-2 text-xs leading-5 text-slate-500">{item.rule_text}</p>}</div><span className="text-xs font-bold text-slate-400">Template</span></div>{item.excluded_task_warning && <div className="mt-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-bold text-amber-800"><AlertTriangle size={15} className="mt-0.5 shrink-0"/>This relationship includes an excluded task and requires review.</div>}</article>)}</div>}

    {project.status === "draft" && <section className="rounded-2xl border border-slate-200 bg-white p-4 grid gap-3">
      <h4 className="font-black">Add manual dependency</h4>
      <input className="border rounded p-2" placeholder="Predecessor task ID" value={form.predecessor_project_task_id} onChange={e=>setForm({...form, predecessor_project_task_id:e.target.value})}/>
      <input className="border rounded p-2" placeholder="Successor task ID" value={form.successor_project_task_id} onChange={e=>setForm({...form, successor_project_task_id:e.target.value})}/>
      <input className="border rounded p-2" placeholder="Reason required" value={form.reason} onChange={e=>setForm({...form, reason:e.target.value})}/>
      <Button onClick={async()=>{try{await projectsApi.createDependency(project.id,form); await load()}catch(e){setError(e.message)}}}>Create</Button>
    </section>}
    {data.total > 0 && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-bold text-emerald-800"><Check className="mr-2 inline" size={16}/>{data.total} dependencies generated. Retry creates no duplicates.</div>}
  </div>;
}
