import { useMemo, useState } from "react";
import { Boxes, Check, PackageOpen, Search, Wrench, X } from "lucide-react";

const typeMeta = {
  material: { label: "Materials", icon: PackageOpen, accent: "amber" },
  service: { label: "Services", icon: Wrench, accent: "blue" },
};

export function CategorySelector({ categories = [], selected = [], onChange, error }) {
  const [activeType, setActiveType] = useState("material");
  const [query, setQuery] = useState("");
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const availableCategories = useMemo(() => categories.filter(category => category.active !== false || selected.includes(category.id)), [categories, selected]);
  const categoryById = useMemo(() => Object.fromEntries(categories.map(category => [category.id, category])), [categories]);
  const childrenByParent = useMemo(() => availableCategories.reduce((result, category) => {
    if (category.parent_id) (result[category.parent_id] ||= []).push(category);
    return result;
  }, {}), [availableCategories]);

  const roots = useMemo(() => availableCategories
    .filter(category => !category.parent_id && category.category_type === activeType)
    .filter(category => {
      const needle = query.trim().toLowerCase();
      if (!needle) return true;
      return category.name.toLowerCase().includes(needle)
        || (childrenByParent[category.id] || []).some(child => child.name.toLowerCase().includes(needle));
    }), [activeType, availableCategories, childrenByParent, query]);

  const selectedSummary = useMemo(() => selected
    .map(id => categoryById[id])
    .filter(Boolean)
    .filter(category => category.parent_id || !(childrenByParent[category.id] || []).some(child => selectedSet.has(child.id))),
  [categoryById, childrenByParent, selected, selectedSet]);

  function commit(next) {
    onChange?.([...next]);
  }

  function toggle(category) {
    const next = new Set(selectedSet);
    if (next.has(category.id)) {
      next.delete(category.id);
      if (!category.parent_id) (childrenByParent[category.id] || []).forEach(child => next.delete(child.id));
      if (category.parent_id && !(childrenByParent[category.parent_id] || []).some(child => next.has(child.id))) next.delete(category.parent_id);
    } else {
      next.add(category.id);
      if (category.parent_id) next.add(category.parent_id);
    }
    commit(next);
  }

  function selectedCount(type) {
    return selected.filter(id => categoryById[id]?.category_type === type).length;
  }

  return (
    <section className={`col-span-full overflow-hidden rounded-2xl border bg-white ${error ? "border-rose-300 ring-4 ring-rose-50" : "border-slate-200"}`}>
      {selected.map(id => <input key={id} type="hidden" name="category_ids" value={id}/>) }
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-black text-slate-950"><Boxes size={18} className="text-blue-700"/> Categories and capabilities</div>
          <p className="mt-1 text-xs leading-5 text-slate-500">Choose a main capability or a more precise subcategory.</p>
        </div>
        <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-black text-white">{selectedSummary.length} selected</span>
      </header>

      <div className="grid gap-4 p-5">
        <div className="flex flex-wrap items-center gap-2">
          {Object.entries(typeMeta).map(([type, meta]) => {
            const Icon = meta.icon;
            const active = activeType === type;
            return <button key={type} type="button" onClick={() => setActiveType(type)} className={`flex min-h-11 items-center gap-2 rounded-xl border px-4 text-sm font-black transition ${active ? type === "material" ? "border-amber-300 bg-amber-50 text-amber-900 shadow-sm" : "border-blue-300 bg-blue-50 text-blue-900 shadow-sm" : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"}`}><Icon size={17}/>{meta.label}<span className={`rounded-full px-2 py-0.5 text-[11px] ${active ? "bg-white/80" : "bg-slate-100"}`}>{selectedCount(type)}</span></button>;
          })}
          <label className="ml-auto flex min-h-11 min-w-56 flex-1 items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 text-slate-500 focus-within:border-blue-400 focus-within:bg-white max-[640px]:ml-0 max-[640px]:w-full"><Search size={16}/><input className="min-h-0 w-full border-0 bg-transparent p-0 text-sm outline-none" value={query} onChange={event => setQuery(event.target.value)} placeholder={`Search ${typeMeta[activeType].label.toLowerCase()}`}/></label>
        </div>

        {selectedSummary.length > 0 && <div className="flex flex-wrap gap-2 rounded-xl bg-slate-50 p-3">{selectedSummary.map(category => <button type="button" key={category.id} onClick={() => toggle(category)} className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-black ${category.category_type === "material" ? "bg-amber-100 text-amber-900" : "bg-blue-100 text-blue-900"}`}>{category.name}<X size={13}/></button>)}</div>}

        <div className="grid grid-cols-2 gap-3 max-[720px]:grid-cols-1">
          {roots.map(root => {
            const children = (childrenByParent[root.id] || []).filter(child => !query.trim() || child.name.toLowerCase().includes(query.trim().toLowerCase()) || root.name.toLowerCase().includes(query.trim().toLowerCase()));
            const rootSelected = selectedSet.has(root.id);
            const material = root.category_type === "material";
            return <article key={root.id} className={`rounded-2xl border p-4 transition ${rootSelected ? material ? "border-amber-300 bg-amber-50/70" : "border-blue-300 bg-blue-50/70" : "border-slate-200 bg-white hover:border-slate-300"}`}>
              <label className="flex cursor-pointer items-start gap-3">
                <input type="checkbox" className="sr-only" checked={rootSelected} onChange={() => toggle(root)}/>
                <span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-lg border ${rootSelected ? material ? "border-amber-500 bg-amber-500 text-white" : "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white text-transparent"}`}><Check size={15}/></span>
                <span className="min-w-0"><strong className="block text-sm text-slate-950">{root.name}</strong><small className="mt-1 block text-xs leading-4 text-slate-500">{root.description || (children.length ? `${children.length} available subcategories` : `Select this ${root.category_type} capability`)}</small></span>
              </label>
              {children.length > 0 && <div className="mt-4 flex flex-wrap gap-2 border-t border-black/5 pt-3">{children.map(child => <label key={child.id} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs font-bold transition ${selectedSet.has(child.id) ? material ? "border-amber-300 bg-white text-amber-900" : "border-blue-300 bg-white text-blue-900" : "border-slate-200 bg-white/70 text-slate-600 hover:border-slate-300"}`}><input type="checkbox" checked={selectedSet.has(child.id)} onChange={() => toggle(child)} className="size-4 rounded border-slate-300 accent-blue-700"/>{child.name}</label>)}</div>}
            </article>;
          })}
        </div>

        {!roots.length && <div className="grid min-h-28 place-items-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 text-center"><div><PackageOpen className="mx-auto text-slate-400"/><p className="mt-2 text-sm font-bold text-slate-600">No matching {typeMeta[activeType].label.toLowerCase()}</p></div></div>}
        {error && <p className="text-sm font-bold text-rose-700">{error}</p>}
      </div>
    </section>
  );
}