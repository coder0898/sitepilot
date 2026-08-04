import { useState } from "react";
import { Building2, ChevronDown, ChevronRight, Link2, MessageCircle, Phone, ShieldCheck, UserRound } from "lucide-react";
import { Modal, Pill } from "../../../components/ui";
import { CategorySelector } from "./CategorySelector";

const cleanPhone = (value = "") => value.replace(/[^\d+]/g, "");
const statusLabel = value => ({ active: "Active", inactive: "Inactive", on_hold: "On hold", blocked_by_parent: "Blocked by parent" }[value] || value);
const inputClass = "min-h-12 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-50";

export function QuickActions({ contact, compact = false }) {
  if (!contact) return <span className="text-xs font-bold text-slate-400">No contact</span>;
  return <div className={`flex flex-wrap gap-2 max-[720px]:col-start-2 ${compact ? "[&_span]:hidden" : ""}`}>
    <a className="flex min-h-10 items-center gap-2 rounded-xl bg-blue-50 px-3 text-xs font-black text-blue-700 transition hover:bg-blue-100" href={`tel:${cleanPhone(contact.phone)}`} onClick={event => event.stopPropagation()}><Phone size={16}/><span>Call</span></a>
    <a className="flex min-h-10 items-center gap-2 rounded-xl bg-emerald-50 px-3 text-xs font-black text-emerald-700 transition hover:bg-emerald-100" href={`https://wa.me/${cleanPhone(contact.whatsapp || contact.phone).replace("+", "")}`} target="_blank" rel="noreferrer" onClick={event => event.stopPropagation()}><MessageCircle size={16}/><span>WhatsApp</span></a>
  </div>;
}

export function Metric({ icon, value, label, tone }) {
  return <article className={`grid min-h-28 grid-cols-[auto_1fr] items-center gap-x-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm [&>span]:row-span-2 [&>span]:grid [&>span]:size-11 [&>span]:place-items-center [&>span]:rounded-xl [&>span]:bg-blue-50 [&>span]:text-blue-700 [&>strong]:text-3xl [&>small]:font-bold [&>small]:text-slate-500 ${tone}`}><span>{icon}</span><strong>{value}</strong><small>{label}</small></article>;
}

export function QuickCard({ icon, title, text, onClick }) {
  return <button onClick={onClick}><span>{icon}</span><strong>{title}</strong><small>{text}</small></button>;
}

function CategoryPills({ vendor }) {
  return <div className="mt-2 flex flex-wrap gap-1">{(vendor.categories || [vendor.category]).slice(0, 3).map(category => <Pill key={category}>{category}</Pill>)}</div>;
}

export function ContractorGroup({ main, children, primaryFor, isOpen, toggle, select, showChildren }) {
  return <article className="border-b border-slate-100 last:border-0">
    <div className="grid cursor-pointer grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 p-4 transition hover:bg-blue-50/60 max-[720px]:grid-cols-[auto_minmax(0,1fr)]" onClick={() => select(main.id)}>
      <button className="grid size-9 place-items-center rounded-lg bg-slate-100 p-0 text-slate-600 shadow-none" onClick={event => { event.stopPropagation(); toggle(main.id); }} aria-label={isOpen ? "Collapse sub-vendors" : "Expand sub-vendors"}>{isOpen ? <ChevronDown/> : <ChevronRight/>}</button>
      <div className="grid size-12 shrink-0 place-items-center rounded-xl bg-blue-100 font-black text-blue-700">{main.name.slice(0, 2).toUpperCase()}</div>
      <div className="min-w-0 [&>div]:flex [&>div]:flex-wrap [&>div]:items-center [&>div]:gap-2 [&_h3]:m-0 [&_h3]:text-base [&_small]:mt-1 [&_small]:block [&_small]:text-xs [&_small]:text-slate-500"><div><h3>{main.name}</h3><Pill tone="blue">Main vendor</Pill><Pill tone={main.status === "active" ? "green" : "orange"}>{statusLabel(main.status)}</Pill></div><CategoryPills vendor={main}/><small>{children.length} sub-vendor{children.length === 1 ? "" : "s"} · {primaryFor(main.id)?.name || "No primary contact"}</small></div>
      <QuickActions contact={primaryFor(main.id)} compact/>
    </div>
    {showChildren && isOpen && <div className="border-t border-slate-100 bg-slate-50/60 pl-10 max-[720px]:pl-3">{children.map(({ relation, vendor }) => <div className="grid cursor-pointer grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 p-4 transition hover:bg-blue-50/60 max-[720px]:grid-cols-[auto_minmax(0,1fr)]" key={relation.id} onClick={() => select(vendor.id)}><span className="text-slate-400"><Link2/></span><div className="grid size-12 shrink-0 place-items-center rounded-xl bg-emerald-100 font-black text-emerald-700">{vendor.name.slice(0, 2).toUpperCase()}</div><div className="min-w-0 [&>div]:flex [&>div]:flex-wrap [&>div]:items-center [&>div]:gap-2 [&_h4]:m-0 [&_small]:mt-1 [&_small]:block [&_small]:text-xs [&_small]:text-slate-500"><div><h4>{vendor.name}</h4><Pill tone="green">Sub-vendor</Pill><Pill tone={(vendor.effective_status || vendor.status) === "active" ? "green" : "orange"}>{statusLabel(vendor.effective_status || vendor.status)}</Pill></div><CategoryPills vendor={vendor}/><small>{primaryFor(vendor.id)?.name || "No primary contact"}</small></div><QuickActions contact={primaryFor(vendor.id)} compact/></div>)}{!children.length && <p className="m-0 p-4 text-sm text-slate-500">No linked sub-vendors.</p>}</div>}
  </article>;
}

export function FlatContractor({ vendor, primary, select }) {
  return <article className="border-b border-slate-100 last:border-0"><div className="grid cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 p-4 transition hover:bg-blue-50/60 max-[720px]:grid-cols-[auto_minmax(0,1fr)]" onClick={() => select(vendor.id)}><div className="grid size-12 shrink-0 place-items-center rounded-xl bg-emerald-100 font-black text-emerald-700">{vendor.name.slice(0, 2).toUpperCase()}</div><div className="min-w-0 [&>div]:flex [&>div]:flex-wrap [&>div]:items-center [&>div]:gap-2 [&_h3]:m-0 [&_small]:mt-1 [&_small]:block [&_small]:text-xs [&_small]:text-slate-500"><div><h3>{vendor.name}</h3><Pill tone={vendor.engagement_type === "migration_pending" ? "orange" : "green"}>{vendor.engagement_type === "migration_pending" ? "Parent required" : "Sub-vendor"}</Pill><Pill tone={(vendor.effective_status || vendor.status) === "active" ? "green" : "orange"}>{statusLabel(vendor.effective_status || vendor.status)}</Pill></div><CategoryPills vendor={vendor}/><small>{primary?.name || "No primary contact"}</small></div><QuickActions contact={primary} compact/></div></article>;
}

function SectionHeading({ icon: Icon, eyebrow, title, text }) {
  return <header className="col-span-full flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-950 text-white"><Icon size={18}/></span><div><p className="text-[11px] font-black uppercase tracking-[0.18em] text-blue-700">{eyebrow}</p><h3 className="mt-1 text-lg font-black text-slate-950">{title}</h3>{text && <p className="mt-1 text-sm leading-6 text-slate-500">{text}</p>}</div></header>;
}

function VendorForm({ vendor, categories, fixedMainVendor, includeContact, submitLabel, onSubmit }) {
  const [selectedCategories, setSelectedCategories] = useState(vendor?.category_ids || []);
  const [categoryError, setCategoryError] = useState("");

  function submit(event) {
    if (!selectedCategories.length) {
      event.preventDefault();
      setCategoryError("Select at least one category.");
      return;
    }
    setCategoryError("");
    onSubmit(event);
  }

  return <form className="grid grid-cols-2 gap-5 max-[720px]:grid-cols-1" onSubmit={submit}>
    {fixedMainVendor && <div className="col-span-full flex items-center gap-4 rounded-2xl border border-blue-200 bg-blue-50 p-4"><span className="grid size-11 place-items-center rounded-xl bg-blue-700 text-white"><Building2 size={20}/></span><div><span className="text-[11px] font-black uppercase tracking-[0.16em] text-blue-700">Approved parent vendor</span><strong className="mt-1 block text-slate-950">{fixedMainVendor.name}</strong></div><ShieldCheck className="ml-auto text-blue-700"/><input type="hidden" name="main_contractor_id" value={fixedMainVendor.id}/></div>}

    <section className="col-span-full grid grid-cols-2 gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-5 max-[720px]:grid-cols-1">
      <SectionHeading icon={Building2} eyebrow="Company" title="Vendor profile" text="Core identity and current availability."/>
      <label className="grid gap-2 text-sm font-black text-slate-700">Company name<input className={inputClass} name="name" defaultValue={vendor?.name || ""} required/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">Status<select className={inputClass} name="status" defaultValue={vendor?.status || "active"}><option value="active">Active</option><option value="on_hold">On hold</option><option value="inactive">Inactive</option></select></label>
    </section>

    <CategorySelector categories={categories} selected={selectedCategories} onChange={value => { setSelectedCategories(value); setCategoryError(""); }} error={categoryError}/>

    {includeContact && <section className="col-span-full grid grid-cols-2 gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-5 max-[720px]:grid-cols-1">
      <SectionHeading icon={UserRound} eyebrow="Primary contact" title="Who should the site team call?" text="This contact is created as the vendor's primary person."/>
      <label className="grid gap-2 text-sm font-black text-slate-700">Contact name<input className={inputClass} name="contact_person" required/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">Designation<input className={inputClass} name="designation" placeholder="Site supervisor, owner…"/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">Phone<input className={inputClass} name="phone" inputMode="tel" required/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">WhatsApp<input className={inputClass} name="whatsapp" inputMode="tel" placeholder="Use phone number if blank"/></label>
    </section>}

    <section className="col-span-full grid grid-cols-2 gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-5 max-[720px]:grid-cols-1">
      <SectionHeading icon={ShieldCheck} eyebrow="Business details" title="Compliance and communication" text="Optional information that helps your operations team."/>
      <label className="grid gap-2 text-sm font-black text-slate-700">Email<input className={inputClass} name="email" type="email" defaultValue={vendor?.email || ""}/></label>
      <label className="grid gap-2 text-sm font-black text-slate-700">GST number<input className={inputClass} name="gst_number" defaultValue={vendor?.gst_number || ""}/></label>
      <label className="col-span-full grid gap-2 text-sm font-black text-slate-700 max-[720px]:col-span-1">Address<textarea className={`${inputClass} min-h-24 resize-y`} name="address" defaultValue={vendor?.address || ""}/></label>
      <label className="col-span-full grid gap-2 text-sm font-black text-slate-700 max-[720px]:col-span-1">Internal notes<textarea className={`${inputClass} min-h-24 resize-y`} name="notes" defaultValue={vendor?.notes || ""} placeholder="Scope, working preferences, important context…"/></label>
    </section>

    <div className="sticky bottom-0 col-span-full -mx-6 -mb-6 flex justify-end border-t border-slate-200 bg-white/95 px-6 py-4 backdrop-blur max-[720px]:mx-0 max-[720px]:mb-0"><button className="min-h-12 rounded-xl bg-blue-700 px-6 font-black text-white shadow-[0_10px_24px_rgba(29,78,216,0.22)] transition hover:bg-blue-800">{submitLabel}</button></div>
  </form>;
}

export function CompanyModal({ title, categories, fixedMainContractor, onClose, onSubmit }) {
  return <Modal className="max-w-5xl" title={title} subtitle={fixedMainContractor ? "Create a sub-vendor inside the approved parent relationship." : "Create a structured vendor profile for project and task assignment."} onClose={onClose}><VendorForm categories={categories} fixedMainVendor={fixedMainContractor} includeContact submitLabel={fixedMainContractor ? "Create sub-vendor" : "Create main vendor"} onSubmit={onSubmit}/></Modal>;
}

export function ProfileModal({ vendor, categories, onClose, onSubmit }) {
  return <Modal className="max-w-5xl" title={`Edit ${vendor.name}`} subtitle="Update company details, categories and assignment availability." onClose={onClose}><VendorForm vendor={vendor} categories={categories} submitLabel="Save vendor changes" onSubmit={onSubmit}/></Modal>;
}