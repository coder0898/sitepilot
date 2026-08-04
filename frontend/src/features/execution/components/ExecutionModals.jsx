import { useState } from "react";
import { Archive, ArrowRight, BriefcaseBusiness, ClipboardList, Eye, History, Layers3, LayoutTemplate, PackageOpen, Pencil, Plus, RotateCcw, ShieldCheck, Trash2, UserRound, Wrench } from "lucide-react";
import { Button, ConfirmModal, Field, FormActions, FormGrid, Input, Modal, Pill, Select } from "../../../components/ui";

const prettyStatus = value => String(value || "assigned").replaceAll("_", " ");
const assignmentEventLabel = { TASK_ASSIGNED: "Assigned", TASK_REASSIGNED: "Reassigned", TASK_UNASSIGNED: "Returned to internal team" };
const taskFieldClass = "min-h-12 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-100";

export function ProjectSettingsModal({ project, pms, supervisors, submit, remove, close }) {
  const [confirming, setConfirming] = useState(false);
  return <Modal title="Edit project" subtitle="Update ownership and lifecycle status" onClose={close}>
    <form className="grid gap-5" onSubmit={submit}>
      <FormGrid>
        <Field label="Project name"><Input name="name" defaultValue={project.name} required/></Field>
        <Field label="Client"><Input name="client_name" defaultValue={project.client_name} required/></Field>
        <Field label="Location"><Input name="location" defaultValue={project.location} required/></Field>
        <Field label="Area"><Input name="area" defaultValue={project.area || ""}/></Field>
        <Field label="Project Manager"><Select name="project_manager_id" defaultValue={project.project_manager_id} required>{pms.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</Select></Field>
        <Field label="Supervisor"><Select name="supervisor_id" defaultValue={project.supervisor_id} required>{supervisors.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</Select></Field>
        <Field label="Status" className="md:col-span-2"><Select name="status" defaultValue={project.status}><option value="active">Active</option><option value="on_hold">On hold</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></Select></Field>
      </FormGrid>
      <FormActions className="border-t border-slate-100 pt-4 max-[520px]:grid">
        <Button type="button" variant="danger" onClick={() => setConfirming(true)}><Trash2 size={17}/> Delete project and schedule</Button>
        <Button type="submit">Save project</Button>
      </FormActions>
    </form>
    {confirming && <ConfirmModal title="Delete project?" message="This permanently deletes the project, its days, tasks, proofs, and workflow history." confirmLabel="Delete project" onClose={() => setConfirming(false)} onConfirm={remove}/>} 
  </Modal>;
}export function ProjectModal({ user, pms, supervisors, templates, submit, close }) { const [templateId, setTemplateId] = useState(templates[0]?.id || ""); const selected = templates.find(item => item.id === templateId); return <Modal title="Create project from template" subtitle="Standard tasks will be generated automatically. Add task is only for exceptions." onClose={close}><form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white two-col grid-cols-2 max-[720px]:grid-cols-1" onSubmit={submit}><label className="full-field col-span-full max-[720px]:col-span-1">Execution template<select name="template_id" value={templateId} onChange={event => setTemplateId(event.target.value)} required><option value="" disabled>Select a template</option>{templates.map(template => <option value={template.id} key={template.id}>{template.name} - {template.duration_days} days - {template.tasks.length} tasks</option>)}</select></label>{selected && <div className="full-field col-span-full max-[720px]:col-span-1 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"><strong>{selected.tasks.length} standard tasks will be created automatically</strong><p className="mt-1">Material requirements and reminder preferences are saved with each task for the future WhatsApp workflow.</p></div>}<label>Project name<input name="name" required/></label><label>Client<input name="client_name" required/></label><label>Location<input name="location" required/></label><input type="hidden" name="project_type" value={selected?.project_type || "Interior Fit-out"}/><input type="hidden" name="duration_days" value={selected?.duration_days || 3}/><label>Start date<input type="date" name="start_date" required/></label>{user.role !== "project_manager" && <label>Project Manager<select name="project_manager_id" required><option value="">Select PM</option>{pms.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>}<label>Supervisor<select name="supervisor_id" required><option value="">Select supervisor</option>{supervisors.map(item => <option value={item.id} key={item.id}>{item.name}{item.phone ? "" : " - phone missing"}</option>)}</select></label><label>Area<input name="area"/></label><button className="full-field col-span-full max-[720px]:col-span-1">Create schedule with {selected?.tasks.length || 0} tasks</button></form></Modal>; }export function TaskModal({ project, day, task, supervisors, mains, subsFor, categories = [], submit, close }) {
  const categoryById = Object.fromEntries(categories.map(item => [item.id, item]));
  const initialCategory = categoryById[task?.category_id];
  const [categoryType, setCategoryType] = useState(initialCategory?.category_type || "service");
  const [categoryId, setCategoryId] = useState(task?.category_id || "");
  const [subcategoryId, setSubcategoryId] = useState(task?.subcategory_id || "");
  const [main, setMain] = useState(task?.assigned_contractor_id || "");
  const [sub, setSub] = useState(task?.assigned_subcontractor_id || "");
  const [reminder, setReminder] = useState(task?.material_reminder || false);
  const roots = categories.filter(item => !item.parent_id && item.category_type === categoryType && item.active !== false);
  const children = categories.filter(item => item.parent_id === categoryId && item.active !== false);
  const selectedCategory = categoryById[subcategoryId] || categoryById[categoryId];
  const requiredCategoryId = subcategoryId || categoryId;
  const vendorMatches = vendor => !requiredCategoryId || vendor.category_ids?.includes(requiredCategoryId);
  const matchingSubsFor = mainId => subsFor(mainId).filter(vendor => vendorMatches(vendor));
  const eligibleMains = mains.filter(vendor => vendorMatches(vendor) || matchingSubsFor(vendor.id).length > 0);
  const mappedMains = eligibleMains.filter(vendor => vendor.project_ids?.includes(project.id));
  const availableMains = eligibleMains.filter(vendor => !vendor.project_ids?.includes(project.id));
  const selectedMain = mains.find(vendor => vendor.id === main);
  const mainMatchesDirectly = selectedMain ? vendorMatches(selectedMain) : false;
  const requiresMatchingSub = Boolean(main && requiredCategoryId && !mainMatchesDirectly);
  const eligibleSubs = main ? matchingSubsFor(main) : [];
  const assignmentChanged = main !== (task?.assigned_contractor_id || "") || sub !== (task?.assigned_subcontractor_id || "");
  const isReassignment = Boolean(task && (task.assigned_contractor_id || task.assigned_subcontractor_id) && assignmentChanged);

  function changeType(nextType) {
    setCategoryType(nextType);
    setCategoryId("");
    setSubcategoryId("");
    setMain("");
    setSub("");
  }

  function changeCategory(nextId) {
    setCategoryId(nextId);
    setSubcategoryId("");
    setMain("");
    setSub("");
  }

  return <Modal className="max-w-5xl rounded-[28px]" title={task ? "Edit task" : "Add exceptional task - Day " + day.day_no} subtitle={task?.template_task_id ? "Template work order - changes apply only to this project." : "Create only work missing from the approved project template."} bodyClassName="p-0" onClose={close}>
    <form onSubmit={submit} className="bg-slate-50">
      <input type="hidden" name="project_id" value={project.id}/>
      <input type="hidden" name="day_id" value={day.id}/>
      <input type="hidden" name="category" value={selectedCategory?.name || task?.category || "General"}/>
      <input type="hidden" name="category_id" value={categoryId}/>
      <input type="hidden" name="subcategory_id" value={subcategoryId}/>

      <div className="grid gap-5 p-6 max-[640px]:p-4">
        <section className="grid gap-4 rounded-3xl border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,.05)]">
          <header className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-950 text-white"><ClipboardList size={18}/></span><div><p className="text-[10px] font-black uppercase tracking-[.18em] text-blue-700">Work order</p><h3 className="mt-1 text-lg font-black text-slate-950">Task essentials</h3></div></header>
          <div className="grid grid-cols-[minmax(0,1fr)_220px] gap-4 max-[680px]:grid-cols-1">
            <label className="grid gap-2 text-sm font-black text-slate-700">Task title<input className={taskFieldClass} name="title" defaultValue={task?.title || ""} required/></label>
            <label className="grid gap-2 text-sm font-black text-slate-700">Priority<select className={taskFieldClass} name="priority" defaultValue={task?.priority || "medium"}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
          </div>
        </section>

        <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_16px_45px_rgba(15,23,42,.05)]">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4"><div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-700 text-white"><Layers3 size={18}/></span><div><p className="text-[10px] font-black uppercase tracking-[.18em] text-blue-700">Classification</p><h3 className="mt-1 text-lg font-black text-slate-950">Category and subcategory</h3><p className="mt-1 text-xs text-slate-500">This controls which vendors are eligible for assignment.</p></div></div>{task?.category_id ? <Pill tone="green">Structured</Pill> : <Pill tone="orange">Classification required</Pill>}</header>
          <div className="grid gap-4 p-5">
            <div className="grid grid-cols-2 gap-2">{[["material", PackageOpen, "Material"], ["service", Wrench, "Service"]].map(([value, Icon, label]) => <button type="button" key={value} onClick={() => changeType(value)} className={"min-h-11 items-center justify-center gap-2 rounded-xl border text-sm font-black transition " + (categoryType === value ? "flex border-blue-700 bg-blue-700 text-white shadow-lg shadow-blue-700/20" : "flex border-slate-200 bg-white text-slate-600 hover:border-blue-300 hover:text-blue-700")}><Icon size={17}/>{label}</button>)}</div>
            <div className="grid grid-cols-2 gap-4 max-[680px]:grid-cols-1">
              <label className="grid gap-2 text-sm font-black text-slate-700">Main category<select className={taskFieldClass} value={categoryId} onChange={event => changeCategory(event.target.value)} required><option value="">Select {categoryType} category</option>{roots.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
              <label className="grid gap-2 text-sm font-black text-slate-700">Subcategory<select className={taskFieldClass} value={subcategoryId} onChange={event => { setSubcategoryId(event.target.value); setMain(""); setSub(""); }} disabled={!categoryId || !children.length}><option value="">{children.length ? "Main category only" : "No subcategories available"}</option>{children.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
            </div>
            {task?.category && !task?.category_id && <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">Legacy category: <strong>{task.category}</strong>. Select its approved structured replacement before saving.</div>}
          </div>
        </section>

        <section className="grid gap-4 rounded-3xl border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,.05)]">
          <header className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-emerald-600 text-white"><BriefcaseBusiness size={18}/></span><div><p className="text-[10px] font-black uppercase tracking-[.18em] text-emerald-700">Accountability</p><h3 className="mt-1 text-lg font-black text-slate-950">Assignment</h3><p className="mt-1 text-xs text-slate-500">{requiredCategoryId ? eligibleMains.length + " eligible main vendor" + (eligibleMains.length === 1 ? "" : "s") + " (directly or through a matching sub-vendor)" : "Choose a category to filter eligible vendors."}</p></div></header>
          <div className="grid grid-cols-2 gap-4 max-[680px]:grid-cols-1">
            <label className="grid gap-2 text-sm font-black text-slate-700">Supervisor<select className={taskFieldClass} name="assigned_supervisor_id" defaultValue={task?.assigned_supervisor_id || project.supervisor_id} required>{supervisors.map(item => <option value={item.id} key={item.id}>{item.name}{item.phone ? "" : " - phone missing"}</option>)}</select></label>
            <label className="grid gap-2 text-sm font-black text-slate-700">Main vendor<select className={taskFieldClass} name="assigned_contractor_id" value={main} onChange={event => { setMain(event.target.value); setSub(""); }} disabled={!categoryId}><option value="">Internal task / no vendor</option>{mappedMains.length > 0 && <optgroup label="Project vendors">{mappedMains.map(item => <option value={item.id} key={item.id}>{item.name}{vendorMatches(item) ? "" : " - via matching sub-vendor"}</option>)}</optgroup>}{availableMains.length > 0 && <optgroup label="Available - add to project on assignment">{availableMains.map(item => <option value={item.id} key={item.id}>{item.name}{vendorMatches(item) ? "" : " - via matching sub-vendor"}</option>)}</optgroup>}</select></label>
            <label className="grid gap-2 text-sm font-black text-slate-700">Specific sub-vendor<select className={taskFieldClass} name="assigned_subcontractor_id" value={sub} onChange={event => setSub(event.target.value)} disabled={!main} required={requiresMatchingSub}><option value="">{requiresMatchingSub ? "Select matching sub-vendor (required)" : "Main vendor team"}</option>{eligibleSubs.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
          </div>
          {requiresMatchingSub && <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm leading-5 text-blue-900"><strong>{selectedMain?.name}</strong> is eligible through a matching sub-vendor. Select the responsible sub-vendor to complete this assignment.</div>}
          {categoryId && !eligibleMains.length && <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">No active vendor currently matches this capability. Keep the task internal or update vendor categories in Vendor Hub.</div>}
          {assignmentChanged && <label className="grid gap-2 text-sm font-black text-slate-700">{isReassignment || !main ? "Reason for responsibility change" : "Assignment note (optional)"}<textarea className="min-h-20 w-full resize-y rounded-xl border border-slate-200 px-4 py-3 font-normal outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-100" name="assignment_reason" required={isReassignment || !main} minLength={isReassignment || !main ? 3 : undefined} placeholder={isReassignment ? "Why is this vendor being reassigned?" : !main ? "Why is this task returning to the internal team?" : "Initial scope or coordination note"}/></label>}
        </section>

        <section className="grid gap-4 rounded-3xl border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,.05)]">
          <header className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-amber-500 text-white"><ShieldCheck size={18}/></span><div><p className="text-[10px] font-black uppercase tracking-[.18em] text-amber-700">Site controls</p><h3 className="mt-1 text-lg font-black text-slate-950">Instructions, proof and materials</h3></div></header>
          <label className="grid gap-2 text-sm font-black text-slate-700">Instructions<textarea className="min-h-28 w-full resize-y rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-100" name="instructions" defaultValue={task?.instructions || ""}/></label>
          <label className="grid gap-2 text-sm font-black text-slate-700">Proof requirement<input className={taskFieldClass} name="proof_required" defaultValue={task?.proof_required || ""} placeholder="Example: completed-work photo and checklist"/></label>
          <label className="grid gap-2 text-sm font-black text-slate-700">Materials required<textarea className="min-h-24 w-full resize-y rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-100" name="materials_required" defaultValue={task?.materials_required || ""} placeholder="Gypsum boards, channels, screws..."/></label>
          <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4"><input className="mt-1 size-5 accent-blue-700" type="checkbox" name="material_reminder" checked={reminder} onChange={event => setReminder(event.target.checked)}/><span><strong className="block text-sm text-amber-950">Material reminder</strong><small className="mt-1 block leading-5 text-amber-800">Record that materials should be reminded one day before this task when WhatsApp automation is introduced.</small></span></label>
        </section>
      </div>

      <footer className="sticky bottom-0 z-20 flex items-center justify-between gap-3 border-t border-slate-200 bg-white/95 px-4 py-4 backdrop-blur sm:px-6 max-[520px]:grid"><div className="flex items-center gap-2 text-xs font-bold text-slate-500"><UserRound size={15}/>{task ? "Existing work order" : "New exceptional work"}</div><div className="flex gap-3 max-[520px]:grid"><Button type="button" variant="secondary" onClick={close}>Cancel</Button><Button type="submit">{task ? "Save task" : "Add exceptional task"}</Button></div></footer>
    </form>
  </Modal>;
}
export function TaskAssignmentModal({ task, mains, subsFor, categories = [], submit, close }) {
  const [main, setMain] = useState(task.assigned_contractor_id || "");
  const [sub, setSub] = useState(task.assigned_subcontractor_id || "");
  const requiredCategoryId = task.subcategory_id || task.category_id;
  const vendorMatches = vendor => requiredCategoryId && vendor.category_ids?.includes(requiredCategoryId);
  const matchingSubsFor = mainId => subsFor(mainId).filter(vendorMatches);
  const eligibleMains = mains.filter(vendor => vendorMatches(vendor) || matchingSubsFor(vendor.id).length > 0);
  const mappedMains = eligibleMains.filter(vendor => vendor.project_ids?.includes(task.project_id));
  const availableMains = eligibleMains.filter(vendor => !vendor.project_ids?.includes(task.project_id));
  const selectedMain = mains.find(vendor => vendor.id === main);
  const requiresMatchingSub = Boolean(main && requiredCategoryId && selectedMain && !vendorMatches(selectedMain));
  const eligibleSubs = main ? matchingSubsFor(main) : [];
  const changed = main !== (task.assigned_contractor_id || "") || sub !== (task.assigned_subcontractor_id || "");
  const hadAssignment = Boolean(task.assigned_contractor_id || task.assigned_subcontractor_id);
  const reasonRequired = changed && (hadAssignment || !main);

  return <Modal className="max-w-2xl rounded-[28px]" title="Task responsibility" subtitle="Assign an eligible project vendor without changing the work order." onClose={close}>
    {!requiredCategoryId ? <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-950"><strong>Classification required</strong><p className="mt-2 text-sm leading-6">A Project Manager must classify this legacy task before a vendor can be assigned.</p></div> : <form className="grid gap-5" onSubmit={submit}>
      <section className="rounded-2xl bg-slate-950 p-5 text-white shadow-xl shadow-slate-950/10">
        <p className="text-[10px] font-black uppercase tracking-[.2em] text-blue-300">Current work order</p>
        <h3 className="mt-2 text-xl font-black">{task.title}</h3>
        <p className="mt-2 text-sm text-slate-300">{task.subcontractor_name || task.contractor_name || "Internal team"}</p>
      </section>
      <div className="grid gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-5">
        <label className="grid gap-2 text-sm font-black text-slate-700">Main vendor<select className={taskFieldClass} name="assigned_contractor_id" value={main} onChange={event => { setMain(event.target.value); setSub(""); }}><option value="">Internal task / no vendor</option>{mappedMains.length > 0 && <optgroup label="Project vendors">{mappedMains.map(item => <option value={item.id} key={item.id}>{item.name}{vendorMatches(item) ? "" : " - via matching sub-vendor"}</option>)}</optgroup>}{availableMains.length > 0 && <optgroup label="Available - add to project on assignment">{availableMains.map(item => <option value={item.id} key={item.id}>{item.name}{vendorMatches(item) ? "" : " - via matching sub-vendor"}</option>)}</optgroup>}</select></label>
        <label className="grid gap-2 text-sm font-black text-slate-700">Specific sub-vendor<select className={taskFieldClass} name="assigned_subcontractor_id" value={sub} onChange={event => setSub(event.target.value)} disabled={!main} required={requiresMatchingSub}><option value="">{requiresMatchingSub ? "Select matching sub-vendor" : "Main vendor team"}</option>{eligibleSubs.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
        {requiresMatchingSub && <p className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">This main vendor qualifies through a sub-vendor. Select the responsible sub-vendor.</p>}
        {!eligibleMains.length && <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">No active vendor matches this task classification.</p>}
        {changed && <label className="grid gap-2 text-sm font-black text-slate-700">{reasonRequired ? "Reason for change" : "Assignment note (optional)"}<textarea className="min-h-24 resize-y rounded-xl border border-slate-200 bg-white px-4 py-3 font-normal outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-100" name="reason" required={reasonRequired} minLength={reasonRequired ? 3 : undefined} placeholder={main ? "Scope, coordination, or reassignment reason" : "Why is this returning to the internal team?"}/></label>}
      </div>
      <FormActions><Button type="button" variant="secondary" onClick={close}>Cancel</Button><Button type="submit" disabled={!changed}>Save responsibility</Button></FormActions>
    </form>}
  </Modal>;
}
export function DelayReportModal({ task, submit, close }) {
  const now = new Date();
  const today = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  return <Modal title="Report task delay" subtitle="Tell the PM what stopped the work and propose a realistic recovery date." onClose={close}>
    <form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white" onSubmit={submit}>
      <section className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-950">
        <strong>{task.title}</strong>
        <p className="mt-2 text-sm">Current official date: {new Date(task.effective_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })}</p>
      </section>
      <label>Delay category<select name="category" defaultValue="" required><option value="" disabled>Select reason type</option><option value="material">Material unavailable</option><option value="labour">Labour or crew</option><option value="dependency">Previous work dependency</option><option value="client">Client decision</option><option value="weather">Weather</option><option value="site_condition">Site condition</option><option value="other">Other</option></select></label>
      <label>Proposed recovery date<input type="date" name="proposed_date" min={today} defaultValue={today} required/></label>
      <label>Delay reason and recovery plan<textarea name="reason" minLength="5" required placeholder="Explain what caused the delay and what is needed to restart."/></label>
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">This reports the issue to the PM. It does not change the official task date until the PM confirms a reschedule.</div>
      <button>Send delay report to PM</button>
    </form>
  </Modal>;
}

export function RescheduleTaskModal({ task, submit, close }) {
  const now = new Date();
  const today = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const effectiveDate = task.effective_date || task.rescheduled_date || task.scheduled_date;
  const proposedDate = task.active_delay_report?.proposed_date;
  const nextEffectiveDate = new Date(`${effectiveDate}T00:00:00Z`);
  nextEffectiveDate.setUTCDate(nextEffectiveDate.getUTCDate() + 1);
  const nextDate = nextEffectiveDate.toISOString().slice(0, 10);
  const defaultDate = proposedDate && proposedDate >= today && proposedDate !== effectiveDate
    ? proposedDate
    : effectiveDate >= today ? nextDate : today;
  const [scheduledDate, setScheduledDate] = useState(defaultDate);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const sameDate = scheduledDate === effectiveDate;

  async function confirm(event) {
    event.preventDefault();
    if (sameDate) {
      setError("Revised date must be different from the current scheduled date.");
      return;
    }
    setError("");
    setSaving(true);
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    const result = await submit(payload);
    if (!result?.ok) {
      setError(result?.error || "The revised schedule could not be saved. Please try again.");
      setSaving(false);
    }
  }

  return <Modal title={task.active_delay_report ? "Confirm delayed task schedule" : "Reschedule overdue task"} subtitle="The original planned date remains preserved in audit history." onClose={close}>
    <form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white" onSubmit={confirm}>
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950">
        <strong>{task.title}</strong>
        <p className="mt-2 text-sm">Original date: {new Date(task.scheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })}{task.rescheduled_date ? " / Current revised date: " + new Date(task.rescheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" }) : ""}</p>
      </section>
      {task.active_delay_report && <section className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-950"><strong>Supervisor proposal</strong><p className="mt-2 text-sm">{task.active_delay_report.reason}</p><small className="mt-2 block">Category: {task.active_delay_report.category.replaceAll("_", " ")} / Proposed: {new Date(task.active_delay_report.proposed_date + "T00:00:00").toLocaleDateString("en-GB")}</small></section>}
      <label>Official revised working date<input type="date" name="scheduled_date" min={today} value={scheduledDate} onChange={event => { setScheduledDate(event.target.value); setError(""); }} aria-invalid={sameDate || Boolean(error)} aria-describedby="reschedule-date-help reschedule-error" required/><small id="reschedule-date-help" className="mt-1 block font-medium text-slate-500">Current official date: {new Date(effectiveDate + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })}. Choose a different working date.</small></label>
      <label>PM rescheduling reason<textarea name="reason" minLength="5" required defaultValue={task.active_delay_report?.reason || task.delay_reason || ""} placeholder="Confirm or update the reason for the official schedule change."/></label>
      {(sameDate || error) && <div id="reschedule-error" role="alert" className="rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm font-bold text-rose-800">{error || "Revised date must be different from the current scheduled date."}</div>}
      <button disabled={sameDate || saving} className="disabled:cursor-not-allowed disabled:opacity-60">{saving ? "Saving revised date..." : task.active_delay_report ? "Confirm official revised date" : "Confirm revised date"}</button>
    </form>
  </Modal>;
}
export function TaskDetail({ task, user, categories = [], assign, edit, reportDelay, reschedule, remove, close, canManage, onStatus, onSubmit, onReview }) {
  const [reason, setReason] = useState("");
  const categoryById = Object.fromEntries(categories.map(item => [item.id, item]));
  const mainCategory = categoryById[task.category_id];
  const subcategory = categoryById[task.subcategory_id];
  const isSupervisor = user.role === "supervisor";
  const isAssignedSupervisor = task.assigned_supervisor_id === user.id;
  const canSupervisorUpdate = (isSupervisor || isAssignedSupervisor) && !["submitted","approved","completed"].includes(task.status);
  const isCorrection = task.status === "rejected";
  const overdueLabel = "overdue by " + task.overdue_days + " day" + (task.overdue_days === 1 ? "" : "s");
  return <Modal className="max-w-5xl rounded-[28px]" bodyClassName="p-0" title={task.title} subtitle={"Day " + task.day_no + " - " + (task.is_overdue ? overdueLabel : prettyStatus(task.status))} onClose={close}>
    <div className="grid gap-5 bg-slate-50 p-6 max-[640px]:p-4">
      {task.is_overdue && <section className="rounded-xl border border-rose-300 bg-rose-50 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h4 className="font-black text-rose-950">Schedule missed by {task.overdue_days} day{task.overdue_days === 1 ? "" : "s"}</h4><p className="mt-1 text-sm text-rose-800">The task remains open and needs site action or a controlled revised date.</p></div>{canManage && <Button type="button" size="sm" variant="danger" onClick={reschedule}>Reschedule task</Button>}</div></section>}
      {task.active_delay_report && <section className="rounded-xl border border-amber-300 bg-amber-50 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[11px] font-black uppercase tracking-wider text-amber-700">Awaiting PM confirmation</p><h4 className="mt-1 font-black capitalize text-amber-950">{task.active_delay_report.category.replaceAll("_", " ")}</h4><p className="mt-2 text-sm leading-6 text-amber-900">{task.active_delay_report.reason}</p><small className="mt-2 block text-amber-700">Proposed date: {new Date(task.active_delay_report.proposed_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })} / Reported by {task.active_delay_report.created_by_name}</small></div>{canManage && <Button type="button" size="sm" className="bg-amber-700 hover:bg-amber-800" onClick={reschedule}>Confirm official schedule</Button>}</div></section>}
      <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_16px_45px_rgba(15,23,42,.05)]">
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4"><div><p className="text-[10px] font-black uppercase tracking-[.18em] text-blue-700">Work order summary</p><h3 className="mt-1 text-lg font-black text-slate-950">{subcategory?.name || mainCategory?.name || task.category}</h3></div><div className="flex flex-wrap items-center gap-2"><Pill tone={task.priority === "high" ? "red" : "blue"}>{task.priority} priority</Pill><Pill tone={task.status === "approved" ? "green" : task.status === "rejected" ? "red" : "blue"}>{prettyStatus(task.status)}</Pill><Button type="button" size="sm" variant="secondary" onClick={assign}><BriefcaseBusiness size={15}/>{task.assigned_contractor_id ? "Change responsibility" : "Assign vendor"}</Button></div></header>
        <div className="grid grid-cols-3 gap-px bg-slate-200 max-[760px]:grid-cols-2 max-[480px]:grid-cols-1">{[
          ["Supervisor", task.supervisor_name],
          ["Responsible company", task.subcontractor_name || task.contractor_name || "Internal team"],
          ["Classification", subcategory ? (mainCategory?.name || "") + " / " + subcategory.name : mainCategory?.name || task.category],
          ["Original date", new Date(task.scheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })],
          ["Active date", new Date(task.effective_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })],
          ["Proof required", task.proof_required || "Not specified"],
        ].map(([label, value]) => <article key={label} className="min-w-0 bg-white p-4"><span className="block text-[10px] font-black uppercase tracking-[.15em] text-slate-400">{label}</span><strong className="mt-2 block break-words text-sm leading-6 text-slate-800">{value}</strong></article>)}</div>
      </section>
      {task.rescheduled_date && <section className="rounded-xl border border-amber-200 bg-amber-50 p-4"><h4 className="font-black text-amber-950">Revised schedule</h4><p className="mt-2 text-sm text-amber-900">{task.delay_reason}</p><small className="mt-2 block text-amber-700">Revised by {task.rescheduled_by_name || "SiteOps manager"} / {task.reschedule_count} change{task.reschedule_count === 1 ? "" : "s"}</small></section>}
      <section className="rounded-xl border border-slate-200 bg-slate-50 p-4"><h4 className="font-black text-slate-900">Instructions</h4><p className="mt-2 text-sm leading-6 text-slate-600">{task.instructions || "No instructions added."}</p></section>
      {task.materials_required && <section className="rounded-xl border border-amber-200 bg-amber-50 p-4"><h4 className="font-black text-amber-950">Materials required</h4><p className="mt-2 text-sm text-amber-900">{task.materials_required}</p></section>}
      {task.assignment_history?.length > 0 && <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_16px_45px_rgba(15,23,42,.05)]">
        <header className="flex items-center gap-3 border-b border-slate-100 px-5 py-4"><span className="grid size-10 place-items-center rounded-xl bg-slate-950 text-white"><History size={18}/></span><div><p className="text-[10px] font-black uppercase tracking-[.18em] text-blue-700">Audit trail</p><h4 className="mt-1 font-black text-slate-950">Responsibility history</h4></div></header>
        <div className="grid gap-0">{task.assignment_history.map((item, index) => <article key={item.id} className="relative grid grid-cols-[18px_minmax(0,1fr)] gap-3 border-b border-slate-100 px-5 py-4 last:border-0 max-[520px]:px-4">
          <span className="relative mt-1 grid size-[18px] place-items-center rounded-full bg-blue-700 ring-4 ring-blue-50 after:absolute after:left-1/2 after:top-[18px] after:h-[calc(100%+16px)] after:w-px after:bg-slate-200 last:after:hidden">{index === 0 && <span className="size-1.5 rounded-full bg-white"/>}</span>
          <div className="min-w-0"><div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-sm text-slate-950">{assignmentEventLabel[item.event_type] || prettyStatus(item.event_type)}</strong><time className="text-xs text-slate-400">{new Date(item.created_at).toLocaleString("en-GB")}</time></div>
          <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 text-sm text-slate-600"><span className="font-bold text-slate-800">{item.from_subcontractor_id ? item.from_subcontractor_name : item.from_contractor_name}</span><ArrowRight size={14} className="shrink-0 text-blue-600"/><span className="font-bold text-slate-950">{item.to_subcontractor_id ? item.to_subcontractor_name : item.to_contractor_name}</span></div>
          <p className="mt-2 text-sm leading-6 text-slate-600">{item.reason}</p><small className="mt-1 block text-xs text-slate-400">Changed by {item.changed_by_name}</small></div>
        </article>)}</div>
      </section>}
      {task.rejection_reason && <section className="rounded-xl border border-rose-200 bg-rose-50 p-4"><h4 className="font-black text-rose-900">PM correction requested</h4><p className="mt-2 text-sm text-rose-800">{task.rejection_reason}</p></section>}
      {task.remarks && <section><h4 className="font-black">Supervisor remarks</h4><p className="mt-2 text-sm text-slate-600">{task.remarks}</p>{task.proof_url && <a className="mt-3 inline-flex font-bold text-blue-700" href={window.location.protocol + "//" + window.location.hostname + ":8000" + task.proof_url} target="_blank" rel="noreferrer">Open submitted proof</a>}</section>}
      {canSupervisorUpdate && (
        <section className={isCorrection ? "rounded-2xl border border-rose-300 bg-rose-50 p-5" : "rounded-2xl border border-blue-200 bg-blue-50 p-5"}>
          <h4 className={isCorrection ? "font-black text-rose-950" : "font-black text-blue-950"}>{isCorrection ? "Correct and resubmit" : "Update site work"}</h4>
          {isCorrection && <p className="mt-2 text-sm leading-6 text-rose-800">This task is reopened for correction. Update the remarks and attach revised proof before sending it back to the PM.</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button type="button" onClick={() => onStatus("in_progress")}>{task.active_delay_report ? "Restart work and withdraw delay" : "Start work"}</Button>
            {!task.active_delay_report && <Button type="button" variant="secondary" onClick={reportDelay}>Report delay</Button>}
          </div>
          <form className="mt-5 grid gap-4" onSubmit={onSubmit}>
            <label className="grid gap-2 text-sm font-extrabold text-slate-700">Completion remarks<textarea className="min-h-28 w-full resize-y rounded-xl border border-slate-300 bg-white px-4 py-3 font-normal outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-100" name="remarks" required placeholder="Describe completed work, checks, or site observations"/></label>
            <label className="grid gap-2 text-sm font-extrabold text-slate-700">Proof photo or PDF<input className="w-full cursor-pointer rounded-xl border border-slate-300 bg-white text-sm font-normal text-slate-600 file:mr-4 file:border-0 file:bg-blue-700 file:px-4 file:py-3 file:font-bold file:text-white hover:file:bg-blue-800" type="file" name="proof" accept="image/jpeg,image/png,image/webp,application/pdf" required={Boolean(task.proof_required)}/></label>
            <Button type="submit" className="w-full">{isCorrection ? "Resubmit corrected work" : "Submit work for PM review"}</Button>
          </form>
        </section>
      )}
      {canManage && task.status === "submitted" && <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5"><h4 className="font-black text-emerald-950">PM review</h4><p className="mt-1 text-sm text-emerald-800">Review the proof and supervisor remarks before deciding.</p><textarea className="mt-4 min-h-24 w-full resize-y rounded-xl border border-emerald-200 bg-white px-4 py-3 outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-100" value={reason} onChange={event => setReason(event.target.value)} placeholder="Rejection reason (required only when rejecting)"/><div className="mt-3 flex flex-wrap gap-2"><Button type="button" onClick={() => onReview("approve", "")}>Approve work</Button><Button type="button" variant="danger" disabled={!reason.trim()} onClick={() => onReview("reject", reason)}>Reject with reason</Button></div></section>}
      {task.delay_reports?.length > 0 && <section><h4 className="font-black">Delay report history</h4><div className="mt-3 grid gap-2">{task.delay_reports.map(item => <article key={item.id} className="rounded-xl border border-slate-200 bg-white p-3 text-sm"><div className="flex items-center justify-between gap-3"><strong className="capitalize">{item.category.replaceAll("_", " ")}</strong><Pill tone={item.status === "pending" ? "orange" : item.status === "accepted" ? "green" : "gray"}>{item.status}</Pill></div><p className="mt-2 text-slate-600">{item.reason}</p><small className="text-slate-500">Proposed {new Date(item.proposed_date + "T00:00:00").toLocaleDateString("en-GB")} / {item.created_by_name}</small></article>)}</div></section>}
      {task.reschedule_history?.length > 0 && <section><h4 className="font-black">Schedule history</h4><div className="mt-3 grid gap-2">{task.reschedule_history.map(item => <article key={item.id} className="rounded-xl border border-slate-200 bg-white p-3 text-sm"><strong>{new Date(item.previous_date + "T00:00:00").toLocaleDateString("en-GB")} to {new Date(item.new_date + "T00:00:00").toLocaleDateString("en-GB")}</strong><p className="mt-1 text-slate-600">{item.reason}</p><small className="text-slate-500">{item.created_by_name} / {new Date(item.created_at).toLocaleString("en-GB")}</small></article>)}</div></section>}
      {canManage && <div className="task-detail-actions sticky bottom-2 z-10 flex justify-end gap-2 rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-[0_14px_35px_rgba(15,23,42,.12)] backdrop-blur max-[650px]:grid"><Button type="button" variant="secondary" onClick={edit}>Edit task</Button><Button type="button" variant="danger" onClick={remove}><Trash2 size={18}/> Delete task</Button></div>}
    </div>
  </Modal>;
}export function TemplateView({ templates, open, view, edit, toggle }) {
  return <section className="overflow-hidden rounded-[26px] border border-slate-200 bg-white shadow-[0_18px_50px_rgba(15,23,42,.06)]">
    <header className="flex items-center justify-between gap-4 border-b border-slate-200 px-6 py-5 max-[650px]:grid max-[650px]:px-4">
      <div><p className="m-0 text-[11px] font-black uppercase tracking-[.18em] text-violet-700">Super Admin control</p><h3 className="mt-1 font-serif text-2xl text-slate-950">Execution templates</h3><span className="mt-1 block text-sm text-slate-500">Manage the reusable blueprints used to generate project schedules.</span></div>
      <Button type="button" onClick={open}><Plus size={18}/> New template</Button>
    </header>
    <div className="grid gap-3 p-4">
      {templates.map(template => <article key={template.id} className={"grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 rounded-2xl border p-4 transition max-[760px]:grid-cols-[auto_minmax(0,1fr)] " + (template.active ? "border-slate-200 bg-white hover:border-blue-300 hover:shadow-[0_12px_30px_rgba(37,99,235,.08)]" : "border-slate-200 bg-slate-50 opacity-80")}>
        <span className={"grid size-12 place-items-center rounded-2xl " + (template.active ? "bg-blue-50 text-blue-700" : "bg-slate-200 text-slate-500")}><LayoutTemplate size={23}/></span>
        <button type="button" onClick={() => view(template)} className="min-w-0 bg-transparent p-0 text-left text-slate-900 shadow-none">
          <span className="flex flex-wrap items-center gap-2"><strong className="truncate text-base">{template.name}</strong><Pill tone={template.active ? "green" : "gray"}>{template.active ? "Active" : "Archived"}</Pill></span>
          <small className="mt-1 block text-slate-500">{template.project_type} · {template.duration_days} days · {template.tasks.length} tasks · {template.used_project_count} projects</small>
        </button>
        <div className="flex items-center justify-end gap-2 max-[760px]:col-span-2 max-[760px]:grid max-[760px]:grid-cols-3">
          <Button type="button" variant="secondary" onClick={() => view(template)}><Eye size={16}/><span className="max-[460px]:sr-only">View</span></Button>
          <Button type="button" variant="secondary" onClick={() => edit(template)}><Pencil size={16}/><span className="max-[460px]:sr-only">Edit</span></Button>
          <Button type="button" variant="secondary" onClick={() => toggle(template)}>{template.active ? <Archive size={16}/> : <RotateCcw size={16}/>}<span className="max-[460px]:sr-only">{template.active ? "Archive" : "Reactivate"}</span></Button>
        </div>
      </article>)}
      {!templates.length && <div className="grid min-h-56 place-items-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-slate-500"><div><LayoutTemplate className="mx-auto mb-3 text-violet-600"/><p>No templates created yet.</p></div></div>}
    </div>
  </section>;
}

export function TemplateDetail({ template, categories = [], edit, toggle, remove, close }) {
  const [confirming, setConfirming] = useState(false);
  const categoryById = Object.fromEntries(categories.map(item => [item.id, item]));
  const days = Array.from({ length: template.duration_days }, (_, index) => index + 1);
  const dateValue = template.updated_at || template.created_at;

  return <Modal className="max-w-5xl rounded-[28px]" title="Template details" subtitle="Reusable schedule blueprint · changes apply only to future projects." bodyClassName="p-0" onClose={close}>
    <div className="bg-slate-50">
      <section className="border-b border-slate-200 bg-slate-950 px-6 py-6 text-white max-[640px]:px-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><Pill tone={template.active ? "green" : "gray"}>{template.active ? "Active" : "Archived"}</Pill><span className="text-xs font-bold text-slate-400">{template.project_type}</span></div><h3 className="mt-3 truncate font-serif text-3xl">{template.name}</h3><p className="mt-2 text-sm text-slate-300">{template.duration_days}-day schedule containing {template.tasks.length} classified work orders.</p></div>
          <div className="grid grid-cols-2 gap-2 text-center"><div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3"><strong className="block text-2xl">{template.tasks.length}</strong><small className="text-slate-400">Tasks</small></div><div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3"><strong className="block text-2xl">{template.used_project_count}</strong><small className="text-slate-400">Projects</small></div></div>
        </div>
      </section>

      {template.used_project_count > 0 && <div className="mx-6 mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 max-[640px]:mx-4"><strong>Project history is protected.</strong><p className="mt-1">Editing this blueprint changes future projects only. Existing generated schedules remain unchanged, and this template can be archived but not deleted.</p></div>}

      <section className="grid gap-4 p-6 max-[640px]:p-4">
        <header className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-[10px] font-black uppercase tracking-[.18em] text-blue-700">Day-wise work orders</p><h4 className="mt-1 text-xl font-black text-slate-950">Structured task plan</h4></div>{dateValue && <small className="text-slate-500">Last updated {new Date(dateValue).toLocaleString("en-GB")}</small>}</header>
        <div className="grid gap-4 lg:grid-cols-3">
          {days.map(day => {
            const dayTasks = template.tasks.filter(task => task.day_no === day);
            return <article key={day} className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
              <header className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-3"><strong>Day {day}</strong><span className="rounded-full bg-blue-100 px-2.5 py-1 text-xs font-black text-blue-700">{dayTasks.length}</span></header>
              <div className="grid gap-2 p-3">{dayTasks.map((task, index) => {
                const main = categoryById[task.category_id];
                const sub = categoryById[task.subcategory_id];
                return <div key={task.id || index} className="rounded-xl border border-slate-200 p-3"><div className="flex items-start justify-between gap-2"><strong className="text-sm text-slate-950">{task.title}</strong><Pill tone={task.priority === "high" ? "red" : task.priority === "low" ? "gray" : "blue"}>{task.priority}</Pill></div><p className="mt-2 text-xs font-bold text-slate-600">{main?.category_type === "material" ? "Material" : "Service"} · {main?.name || task.category}</p>{sub && <span className="mt-2 inline-flex rounded-full bg-amber-50 px-2 py-1 text-[11px] font-bold text-amber-800">{sub.name}</span>}{task.instructions && <p className="mt-2 line-clamp-2 text-xs text-slate-500">{task.instructions}</p>}</div>;
              })}{!dayTasks.length && <p className="p-3 text-center text-sm text-slate-400">No tasks</p>}</div>
            </article>;
          })}
        </div>
      </section>
      <footer className="sticky bottom-0 z-20 flex items-center justify-between gap-3 border-t border-slate-200 bg-white/95 px-6 py-4 backdrop-blur max-[700px]:grid max-[640px]:px-4">
        <div className="text-xs text-slate-500">{template.can_delete ? "Unused templates can be permanently deleted." : "Archive this template to remove it from new project creation."}</div>
        <div className="flex flex-wrap justify-end gap-2 max-[520px]:grid max-[520px]:grid-cols-1">
          {template.can_delete && <Button type="button" variant="danger" onClick={() => setConfirming(true)}><Trash2 size={17}/> Delete</Button>}
          <Button type="button" variant="secondary" onClick={toggle}>{template.active ? <Archive size={17}/> : <RotateCcw size={17}/>} {template.active ? "Archive" : "Reactivate"}</Button>
          <Button type="button" onClick={edit}><Pencil size={17}/> Edit template</Button>
        </div>
      </footer>
    </div>
    {confirming && <ConfirmModal title="Delete unused template?" message="This permanently removes the template and its work orders. This action is available only because the template has not generated a project." confirmLabel="Delete template" onClose={() => setConfirming(false)} onConfirm={remove}/>}
  </Modal>;
}

export function TemplateModal({ template = null, categories = [], submit, close }) {
  const editing = Boolean(template);
  const [duration, setDuration] = useState(template?.duration_days || 3);
  const [tasks, setTasks] = useState(() => template?.tasks?.length ? template.tasks.map(item => ({
    ...item,
    key: item.id || crypto.randomUUID(),
    category_id: item.category_id || "",
    subcategory_id: item.subcategory_id || "",
    instructions: item.instructions || "",
    materials_required: item.materials_required || "",
    material_reminder: Boolean(item.material_reminder),
  })) : [{ key: crypto.randomUUID(), day_no: 1, title: "", category_id: "", subcategory_id: "", priority: "medium", instructions: "", materials_required: "", material_reminder: false }]);
  const roots = categories.filter(item => !item.parent_id && item.active !== false);
  const categoryById = Object.fromEntries(categories.map(item => [item.id, item]));
  const addTask = () => setTasks(current => [...current, { key: crypto.randomUUID(), day_no: Math.min(current.length + 1, duration), title: "", category_id: "", subcategory_id: "", priority: "medium", instructions: "", materials_required: "", material_reminder: false }]);
  const updateTask = (key, changes) => setTasks(current => current.map(item => item.key === key ? { ...item, ...changes } : item));
  const removeTask = key => setTasks(current => current.length === 1 ? current : current.filter(item => item.key !== key));

  function handleSubmit(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    submit({
      name: fields.get("name"),
      project_type: fields.get("project_type"),
      duration_days: duration,
      tasks: tasks.map(item => ({
        id: item.id || null,
        day_no: Number(item.day_no),
        title: item.title.trim(),
        category: categoryById[item.subcategory_id || item.category_id]?.name || "General",
        category_id: item.category_id,
        subcategory_id: item.subcategory_id || null,
        priority: item.priority,
        instructions: item.instructions.trim() || null,
        materials_required: item.materials_required.trim() || null,
        material_reminder: item.material_reminder,
        reminder_lead_days: 1,
      })),
    });
  }

  return <Modal className="max-w-5xl rounded-[28px]" title={editing ? "Edit execution template" : "Create structured template"} subtitle={editing ? "Changes apply only to projects created after this update." : "Every generated task receives an approved capability classification."} bodyClassName="p-0" onClose={close}>
    <form className="grid gap-0 bg-slate-50" onSubmit={handleSubmit}>
      <section className="grid grid-cols-[1fr_1fr_180px] gap-4 border-b border-slate-200 bg-white p-6 max-[760px]:grid-cols-1 max-[640px]:p-4">
        <label className="grid gap-2 text-sm font-black text-slate-700">Template name<input className={taskFieldClass} name="name" defaultValue={template?.name || ""} required/></label>
        <label className="grid gap-2 text-sm font-black text-slate-700">Project type<input className={taskFieldClass} name="project_type" defaultValue={template?.project_type || ""} required/></label>
        <label className="grid gap-2 text-sm font-black text-slate-700">Duration<input className={taskFieldClass} type="number" min="1" max="45" value={duration} onChange={event => { const next=Math.max(1,Math.min(45,Number(event.target.value) || 1)); setDuration(next); setTasks(current => current.map(item => ({ ...item, day_no: Math.min(item.day_no, next) }))); }}/></label>
      </section>
      {editing && template.used_project_count > 0 && <div className="mx-6 mt-5 rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900 max-[640px]:mx-4"><strong>Safe template editing</strong><p className="mt-1">{template.used_project_count} existing project(s) will keep their current days, tasks, and classifications.</p></div>}
      <section className="grid gap-4 p-6 max-[640px]:p-4">
        <header className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-[10px] font-black uppercase tracking-[.18em] text-blue-700">Template work orders</p><h3 className="mt-1 text-xl font-black text-slate-950">Classified starter tasks</h3></div><Button type="button" variant="secondary" onClick={addTask}><Plus size={17}/> Add task</Button></header>
        {tasks.map((item, index) => {
          const children = categories.filter(category => category.parent_id === item.category_id && category.active !== false);
          return <article key={item.key} className="grid gap-4 rounded-3xl border border-slate-200 bg-white p-5 shadow-[0_14px_35px_rgba(15,23,42,.05)] max-[640px]:p-4">
            <div className="flex items-center justify-between gap-3"><strong className="text-sm text-slate-950">Task {index + 1}</strong><button type="button" aria-label={"Remove task " + (index + 1)} disabled={tasks.length === 1} onClick={() => removeTask(item.key)} className="grid size-10 place-items-center rounded-xl border border-rose-200 bg-rose-50 text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-35"><Trash2 size={17}/></button></div>
            <div className="grid grid-cols-[100px_minmax(0,1fr)_180px] gap-4 max-[720px]:grid-cols-1">
              <label className="grid gap-2 text-sm font-black text-slate-700">Day<select className={taskFieldClass} value={item.day_no} onChange={event => updateTask(item.key,{ day_no:Number(event.target.value) })}>{Array.from({length:duration},(_,day)=><option key={day+1} value={day+1}>Day {day+1}</option>)}</select></label>
              <label className="grid gap-2 text-sm font-black text-slate-700">Task title<input className={taskFieldClass} value={item.title} onChange={event => updateTask(item.key,{ title:event.target.value })} required/></label>
              <label className="grid gap-2 text-sm font-black text-slate-700">Priority<select className={taskFieldClass} value={item.priority} onChange={event => updateTask(item.key,{ priority:event.target.value })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
            </div>
            <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
              <label className="grid gap-2 text-sm font-black text-slate-700">Main category<select className={taskFieldClass} value={item.category_id} onChange={event => updateTask(item.key,{ category_id:event.target.value, subcategory_id:"" })} required><option value="">Select category</option>{["material","service"].map(type => <optgroup key={type} label={type === "material" ? "Materials" : "Services"}>{roots.filter(category => category.category_type === type).map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</optgroup>)}</select></label>
              <label className="grid gap-2 text-sm font-black text-slate-700">Subcategory<select className={taskFieldClass} value={item.subcategory_id} onChange={event => updateTask(item.key,{ subcategory_id:event.target.value })} disabled={!children.length}><option value="">{children.length ? "Main category only" : "No subcategories"}</option>{children.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
            </div>
            <div className="grid grid-cols-2 gap-4 max-[640px]:grid-cols-1">
              <label className="grid gap-2 text-sm font-black text-slate-700">Instructions<textarea className={taskFieldClass + " min-h-24 resize-y"} value={item.instructions} onChange={event => updateTask(item.key,{ instructions:event.target.value })} placeholder="Approved execution instructions"/></label>
              <label className="grid gap-2 text-sm font-black text-slate-700">Materials required<textarea className={taskFieldClass + " min-h-24 resize-y"} value={item.materials_required} onChange={event => updateTask(item.key,{ materials_required:event.target.value })} placeholder="Materials, tools, or consumables"/></label>
            </div>
            <label className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"><input type="checkbox" className="mt-0.5 size-5 accent-blue-700" checked={item.material_reminder} onChange={event => updateTask(item.key,{ material_reminder:event.target.checked })}/><span><strong className="block">Material reminder required</strong><small className="mt-1 block text-amber-800">Preserve this rule for the future WhatsApp reminder workflow.</small></span></label>
          </article>;
        })}
      </section>
      <footer className="sticky bottom-0 z-20 flex justify-end gap-3 border-t border-slate-200 bg-white/95 px-6 py-4 backdrop-blur max-[520px]:grid max-[640px]:px-4"><Button type="button" variant="secondary" onClick={close}>Cancel</Button><Button type="submit">{editing ? "Save template changes" : "Create structured template"}</Button></footer>
    </form>
  </Modal>;
}