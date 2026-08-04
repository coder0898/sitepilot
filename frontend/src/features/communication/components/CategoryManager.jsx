import { useMemo, useState } from "react";
import { Archive, Boxes, ChevronRight, FolderTree, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { ConfirmModal, Modal, Pill } from "../../../components/ui";

const fieldClass = "min-h-12 w-full rounded-xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-blue-600 focus:ring-4 focus:ring-blue-100";

export function CategoryManager({ categories = [], save, remove, close }) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [draftParentId, setDraftParentId] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const selected = categories.find(item => item.id === selectedId);
  const roots = useMemo(() => categories
    .filter(item => !item.parent_id)
    .filter(item => {
      const needle = query.trim().toLowerCase();
      if (!needle) return true;
      return item.name.toLowerCase().includes(needle)
        || categories.some(child => child.parent_id === item.id && child.name.toLowerCase().includes(needle));
    }), [categories, query]);
  const parent = categories.find(item => item.id === (selected?.parent_id || draftParentId));
  const editing = Boolean(selected);
  const formKey = selected?.id || draftParentId || "new";
  const usageCount = selected?.usage_count || 0;
  const childCount = selected?.child_count || 0;
  const deletionBlocked = usageCount > 0 || childCount > 0;
  const deleteMessage = deleteError || (deletionBlocked
    ? `This category cannot be permanently deleted because it has ${usageCount} active use${usageCount === 1 ? "" : "s"} and ${childCount} subcategor${childCount === 1 ? "y" : "ies"}. Archive it to remove it from new selections while preserving existing vendor, task and template history.`
    : "This category is unused and can be permanently deleted.");

  function beginMain() {
    setSelectedId(null);
    setDraftParentId(null);
  }

  function beginChild(root) {
    setSelectedId(null);
    setDraftParentId(root.id);
  }

  async function submit(event) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const payload = {
      name: data.get("name"),
      parent_id: data.get("parent_id") || null,
      description: data.get("description") || null,
      active: data.get("active") === "true",
    };
    const result = await save(payload, selected?.id);
    if (result?.ok && !selected) {
      setDraftParentId(null);
    }
  }

  async function confirmCategoryRemoval() {
    setDeleteError("");
    const result = deletionBlocked
      ? await save({ name: selected.name, parent_id: selected.parent_id || null, description: selected.description || null, active: false }, selected.id)
      : await remove(selected.id);
    if (result?.ok) {
      setConfirmDelete(false);
      beginMain();
      return;
    }
    setDeleteError(result?.error || "This category could not be updated. Please review its linked records and try again.");
  }

  return <Modal hideHeader className="max-w-6xl rounded-[28px]" bodyClassName="p-0" onClose={close}>
    <div className="overflow-hidden bg-slate-50">
      <header className="relative overflow-hidden bg-slate-950 px-6 py-6 text-white">
        <div className="absolute inset-y-0 right-0 w-72 bg-[radial-gradient(circle_at_center,rgba(37,99,235,.35),transparent_65%)]"/>
        <div className="relative flex items-start justify-between gap-4">
          <div className="flex items-start gap-4">
            <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-blue-600 text-white shadow-lg shadow-blue-950/30"><FolderTree/></span>
            <div><p className="text-[11px] font-black uppercase tracking-[0.18em] text-blue-300">Taxonomy control</p><h2 className="mt-1 text-2xl font-black tracking-tight">Vendor capability categories</h2><p className="mt-1 max-w-2xl text-sm text-slate-300">Manage the two-level capability structure used by vendors, templates and project tasks.</p></div>
          </div>
          <button type="button" onClick={close} className="grid size-11 shrink-0 place-items-center rounded-xl border border-white/15 bg-white/10 text-white hover:bg-white/20" aria-label="Close category manager"><X size={22} strokeWidth={3}/></button>
        </div>
      </header>

      <div className="grid min-h-[620px] grid-cols-[minmax(280px,.85fr)_minmax(0,1.4fr)] max-[820px]:grid-cols-1">
        <aside className="border-r border-slate-200 bg-white p-5 max-[820px]:border-b max-[820px]:border-r-0">
          <label className="flex min-h-11 items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 text-slate-500 focus-within:border-blue-500"><Search size={16}/><input value={query} onChange={event => setQuery(event.target.value)} className="w-full border-0 bg-transparent text-sm outline-none" placeholder="Search categories"/></label>
          <button type="button" onClick={beginMain} className="mt-4 flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 text-sm font-black text-white"><Plus size={16}/> New main category</button>

          <div className="mt-4 grid max-h-[440px] gap-2 overflow-y-auto pr-1">
            {roots.map(root => {
              const children = categories.filter(child => child.parent_id === root.id);
              return <section key={root.id} className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
                <button type="button" onClick={() => setSelectedId(root.id)} className={`flex w-full items-center gap-3 p-3 text-left ${selectedId === root.id ? "bg-blue-50" : "hover:bg-slate-50"}`}>
                  <span className={`grid size-9 shrink-0 place-items-center rounded-xl ${root.active ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-400"}`}><Boxes size={17}/></span>
                  <span className="min-w-0 flex-1"><strong className="block truncate text-sm text-slate-950">{root.name}</strong><small className="mt-0.5 block text-xs text-slate-500">{children.length} subcategories - {root.usage_count || 0} uses</small></span>
                  {!root.active && <Pill tone="gray">Archived</Pill>}<ChevronRight size={16} className="text-slate-400"/>
                </button>
                <div className="border-t border-slate-100 bg-slate-50/60 p-2">
                  {children.map(child => <button type="button" key={child.id} onClick={() => setSelectedId(child.id)} className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm ${selectedId === child.id ? "bg-white font-black text-blue-700 shadow-sm" : "text-slate-600 hover:bg-white"}`}><span className="size-1.5 rounded-full bg-blue-400"/><span className="min-w-0 flex-1 truncate">{child.name}</span>{!child.active && <Archive size={14}/>}</button>)}
                  <button type="button" onClick={() => beginChild(root)} className="mt-1 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-xs font-black text-blue-700 hover:bg-white"><Plus size={14}/> Add subcategory</button>
                </div>
              </section>;
            })}
            {!roots.length && <div className="rounded-2xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">No categories match this view.</div>}
          </div>
        </aside>

        <main className="p-6 max-[640px]:p-4">
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
            <div><p className="text-[11px] font-black uppercase tracking-[0.16em] text-blue-700">{editing ? "Edit category" : parent ? "New subcategory" : "New main category"}</p><h3 className="mt-1 text-2xl font-black text-slate-950">{editing ? selected.name : parent ? `Under ${parent.name}` : "Create category"}</h3></div>
            {editing && <div className="flex gap-2"><button type="button" onClick={() => beginChild(selected.parent_id ? parent : selected)} disabled={Boolean(selected.parent_id) || !selected.active} className="flex min-h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-xs font-black text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"><Plus size={15}/> Add child</button><button type="button" onClick={() => { setDeleteError(""); setConfirmDelete(true); }} className="grid size-10 place-items-center rounded-xl border border-rose-200 bg-rose-50 text-rose-700" aria-label="Delete category"><Trash2 size={16}/></button></div>}
          </div>

          <form key={formKey} onSubmit={submit} className="grid gap-5 rounded-3xl border border-slate-200 bg-white p-6 shadow-[0_20px_60px_rgba(15,23,42,.06)] max-[640px]:p-4">
            <label className="grid gap-2 text-sm font-black text-slate-700">Level<select className={fieldClass} name="parent_id" defaultValue={selected?.parent_id || draftParentId || ""} disabled={Boolean(parent) || Boolean(selected?.child_count)}><option value="">Main category</option>{categories.filter(item => !item.parent_id && item.active && item.id !== selected?.id).map(item => <option value={item.id} key={item.id}>Subcategory of {item.name}</option>)}</select></label>
            {parent && <input type="hidden" name="parent_id" value={parent.id}/>}
            <label className="grid gap-2 text-sm font-black text-slate-700">Category name<input className={fieldClass} name="name" defaultValue={selected?.name || ""} required placeholder="Example: Electrical services"/></label>
            <label className="grid gap-2 text-sm font-black text-slate-700">Description<textarea className="min-h-28 w-full resize-y rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-100" name="description" defaultValue={selected?.description || ""} placeholder="Describe the work, material or capability covered."/></label>
            <label className="grid gap-2 text-sm font-black text-slate-700">Availability<select className={fieldClass} name="active" defaultValue={String(selected?.active ?? true)}><option value="true">Active - available for new mappings</option><option value="false">Archived - preserve history only</option></select></label>
            {editing && <div className="grid grid-cols-4 gap-2 rounded-2xl bg-slate-50 p-4 text-center max-[640px]:grid-cols-2">{[["Vendors", selected.vendor_count], ["Tasks", selected.task_count], ["Templates", selected.template_task_count], ["Children", selected.child_count]].map(([label, value]) => <div key={label}><strong className="block text-lg text-slate-950">{value || 0}</strong><small className="text-xs text-slate-500">{label}</small></div>)}</div>}
            <div className="flex justify-end gap-3 border-t border-slate-100 pt-5 max-[520px]:grid"><button type="button" onClick={close} className="min-h-11 rounded-xl border border-slate-200 bg-white px-5 text-sm font-black text-slate-700">Close</button><button type="submit" className="flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-700 px-5 text-sm font-black text-white shadow-lg shadow-blue-700/20"><Pencil size={16}/>{editing ? "Save category" : "Create category"}</button></div>
          </form>
        </main>
      </div>
    </div>
    {confirmDelete && selected && <ConfirmModal title={deletionBlocked ? "Archive category?" : "Delete category?"} message={deleteMessage} confirmLabel={deletionBlocked ? "Archive category" : "Delete category"} tone={deletionBlocked ? "primary" : "danger"} onClose={() => { setConfirmDelete(false); setDeleteError(""); }} onConfirm={confirmCategoryRemoval}/>}
  </Modal>;
}
