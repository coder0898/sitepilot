import { useEffect, useMemo, useState } from "react";
import { Building2, ChevronDown, ChevronRight, Clock3, ContactRound, Filter, FolderKanban, Link2, MapPinned, MessageCircle, Pencil, Phone, Plus, Search, UserPlus, UsersRound } from "lucide-react";
import { communicationApi } from "../../api/communicationApi";
import { vendorsApi } from "../../api/vendorsApi";
import { ConfirmModal, Modal, Pill } from "../../components/ui";

const emptyHub = { vendors: [], contacts: [], categories: [], projects: [], project_vendors: [], relationships: [], logs: [] };
import { CompanyModal, ContractorDetail, ContractorGroup, FlatContractor, Metric, ProfileModal, QuickCard } from "./components/CommunicationDirectory";

export function CommunicationHubPage({ user, action }) {
  const [hub, setHub] = useState(emptyHub);
  const [query, setQuery] = useState("");
  const [projectId, setProjectId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("all");
  const [selected, setSelected] = useState(null);
  const [expanded, setExpanded] = useState(new Set());
  const [form, setForm] = useState(null);
  const [showFilters, setShowFilters] = useState(false);
  const canManage = user.role !== "supervisor";
  const canCategories = ["super_admin", "admin"].includes(user.role);

  async function load() {
    const data = await communicationApi.get();
    setHub({ ...emptyHub, ...data });
    setExpanded(current => current.size ? current : new Set(data.relationships.map(item => item.main_contractor_id)));
  }
  useEffect(() => { load().catch(() => {}); }, []);

  async function perform(fn, message) {
    let saved = false;
    await action(async () => { await fn(); saved = true; }, message);
    if (saved) { setForm(null); await load(); }
  }
  async function deleteCompany(vendor) {
    await perform(() => vendorsApi.remove(vendor.id), `${vendor.engagement_type === "main" ? "Contractor" : "Subcontractor"} deleted`);
    setSelected(null);
  }
  async function submit(event, fn, message) {
    event.preventDefault();
    await perform(() => fn(Object.fromEntries(new FormData(event.currentTarget))), message);
  }
  async function createCompany(event, mode) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const categoryIds = data.getAll("category_ids");
    const firstCategory = hub.categories.find(item => item.id === categoryIds[0])?.name || "Other";
    const legacy = { name: data.get("name"), category: firstCategory, contact_person: data.get("contact_person"), phone: data.get("phone"), whatsapp: data.get("whatsapp") || null, notes: data.get("notes") || null };
    const profile = { name: legacy.name, engagement_type: mode === "exclusive" ? "exclusive_subcontractor" : mode, status: data.get("status"), category_ids: categoryIds, email: data.get("email") || null, address: data.get("address") || null, gst_number: data.get("gst_number") || null, notes: legacy.notes };
    const contact = { name: legacy.contact_person, designation: data.get("designation") || null, phone: legacy.phone, whatsapp: legacy.whatsapp, is_primary: true };
    await perform(async () => {
      const company = await vendorsApi.create(legacy);
      await communicationApi.updateContractor(company.id, profile);
      await communicationApi.addContact({ ...contact, vendor_id: company.id });
      if (mode === "exclusive") await communicationApi.linkSubcontractor({ main_contractor_id: data.get("main_contractor_id"), subcontractor_id: company.id });
    }, mode === "main" ? "Main contractor added" : mode === "independent" ? "Independent subcontractor added" : "Subcontractor added");
  }  async function updateCompany(event, vendorId) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await perform(() => communicationApi.updateContractor(vendorId, { name: data.get("name"), engagement_type: vendorById[vendorId]?.engagement_type || "main", status: data.get("status"), category_ids: data.getAll("category_ids"), email: data.get("email") || null, address: data.get("address") || null, gst_number: data.get("gst_number") || null, notes: data.get("notes") || null }), "Contractor updated");
  }

  const vendorById = useMemo(() => Object.fromEntries(hub.vendors.map(vendor => [vendor.id, vendor])), [hub.vendors]);
  const childIds = useMemo(() => new Set(hub.relationships.map(item => item.subcontractor_id)), [hub.relationships]);
  const mainContractors = hub.vendors.filter(vendor => vendor.engagement_type === "main");
  const subcontractors = hub.vendors.filter(vendor => vendor.engagement_type !== "main");
  const contactsFor = id => hub.contacts.filter(contact => contact.vendor_id === id);
  const primaryFor = id => contactsFor(id).find(contact => contact.is_primary) || contactsFor(id)[0];
  const childrenFor = id => hub.relationships.filter(item => item.main_contractor_id === id).map(item => ({ relation: item, vendor: vendorById[item.subcontractor_id] })).filter(item => item.vendor);
  const projectsFor = id => { const vendor = vendorById[id]; const parentId = vendor?.engagement_type === "exclusive_subcontractor" ? hub.relationships.find(item => item.subcontractor_id === id)?.main_contractor_id : null; const ids = new Set([id, parentId].filter(Boolean)); return hub.project_vendors.filter(link => ids.has(link.vendor_id)).map(link => hub.projects.find(project => project.id === link.project_id)).filter(Boolean); };
  const projectVendorIds = useMemo(() => new Set(hub.project_vendors.filter(link => !projectId || link.project_id === projectId).map(link => link.vendor_id)), [hub.project_vendors, projectId]);
  const matches = vendor => {
    const text = `${vendor.name} ${(vendor.categories || []).join(" ")} ${contactsFor(vendor.id).map(contact => contact.name).join(" ")}`.toLowerCase();
    return text.includes(query.toLowerCase()) && (!status || vendor.status === status) && (!categoryId || vendor.category_ids?.includes(categoryId));
  };
  const projectMatches = vendor => { if (!projectId || projectVendorIds.has(vendor.id)) return true; if (vendor.engagement_type === "exclusive_subcontractor") { const parentId = hub.relationships.find(item => item.subcontractor_id === vendor.id)?.main_contractor_id; return Boolean(parentId && projectVendorIds.has(parentId)); } return false; };
  const visibleMains = mainContractors.filter(main => {
    const children = childrenFor(main.id).map(item => item.vendor);
    return (projectMatches(main) || children.some(projectMatches)) && (matches(main) || children.some(matches));
  });
  const visibleSubs = subcontractors.filter(vendor => projectMatches(vendor) && matches(vendor));
  const selectedVendor = vendorById[selected];
  const selectedRelationship = hub.relationships.find(item => item.subcontractor_id === selected);
  const toggle = id => setExpanded(current => { const next = new Set(current); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const activeProjects = hub.projects.filter(project => project.status === "active").length;

  return <div className="hub-v2 grid gap-5">
    <section className="hub-intro flex items-end justify-between gap-5 max-[720px]:grid [&_p]:m-0 [&_p]:text-xs [&_p]:font-black [&_p]:uppercase [&_p]:tracking-[0.18em] [&_p]:text-violet-700 [&_h2]:my-2 [&_h2]:font-serif [&_h2]:text-4xl [&_span]:text-slate-500 [&>button]:flex [&>button]:items-center [&>button]:gap-2 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:py-3 [&>button]:font-black [&>button]:text-white"><div><p>Communication Hub</p><h2>Contractors, contacts and site communication</h2><span>A mobile-first directory for every company and team working across your projects.</span></div>{canManage && <button onClick={() => setForm("main")}><Plus size={18}/> Add main contractor</button>}</section>

    <section className="hub-stat-grid grid grid-cols-4 gap-4 max-[900px]:grid-cols-2 max-[520px]:grid-cols-1"><Metric icon={<Building2/>} value={mainContractors.length} label="Main contractors" tone="blue"/><Metric icon={<UsersRound/>} value={subcontractors.length} label="Subcontractors" tone="green"/><Metric icon={<ContactRound/>} value={hub.contacts.length} label="Contacts" tone="violet"/><Metric icon={<FolderKanban/>} value={activeProjects} label="Active projects" tone="orange"/></section>

    <section className="hub-controls relative flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4 max-[720px]:grid"><label className="hub-search flex min-h-12 flex-1 items-center gap-3 rounded-xl border border-slate-200 px-4 text-slate-500 [&_input]:w-full [&_input]:border-0 [&_input]:bg-transparent [&_input]:outline-none"><Search size={17}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search contractor, trade or contact"/></label><button className={`filter-toggle flex min-h-12 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 font-black text-slate-700 [&.active]:border-blue-300 [&.active]:bg-blue-50 [&.active]:text-blue-700 ${showFilters ? "active" : ""}`} onClick={() => setShowFilters(value => !value)}><Filter size={17}/> Filters</button>{showFilters && <div className="hub-filters absolute left-4 right-4 top-[calc(100%+8px)] z-20 grid grid-cols-3 gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-xl max-[720px]:grid-cols-1 [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3"><select value={projectId} onChange={event => setProjectId(event.target.value)}><option value="">All projects</option>{hub.projects.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}</select><select value={categoryId} onChange={event => setCategoryId(event.target.value)}><option value="">All trades</option>{hub.categories.map(category => <option value={category.id} key={category.id}>{category.name}</option>)}</select><select value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option><option value="active">Active</option><option value="on_hold">On hold</option><option value="inactive">Inactive</option></select></div>}</section>

    <div className="hub-content grid grid-cols-1 gap-4"><section className="hub-directory overflow-hidden rounded-2xl border border-slate-200 bg-white"><div className="hub-tabs flex gap-2 overflow-x-auto border-b border-slate-200 p-4 [&_button]:shrink-0 [&_button]:rounded-xl [&_button]:bg-slate-100 [&_button]:px-4 [&_button]:py-3 [&_button]:font-black [&_button]:text-slate-600 [&_button.active]:bg-violet-700 [&_button.active]:text-white"><button className={type === "all" ? "active" : ""} onClick={() => setType("all")}>All</button><button className={type === "main" ? "active" : ""} onClick={() => setType("main")}>Main contractors</button><button className={type === "sub" ? "active" : ""} onClick={() => setType("sub")}>Subcontractors</button></div>
      {type !== "sub" && visibleMains.map(main => <ContractorGroup key={main.id} main={main} children={childrenFor(main.id).filter(({ vendor }) => matches(vendor) && projectMatches(vendor))} primaryFor={primaryFor} isOpen={expanded.has(main.id)} toggle={toggle} select={setSelected} showChildren={type === "all"}/>) }
      {type === "sub" && visibleSubs.map(sub => <FlatContractor key={sub.id} vendor={sub} primary={primaryFor(sub.id)} select={setSelected} />)}
      {((type === "sub" && !visibleSubs.length) || (type !== "sub" && !visibleMains.length)) && <div className="comm-empty p-10 text-center text-slate-500">No contractors match these filters.</div>}
    </section>{selectedVendor && <Modal className="contractor-detail-modal max-w-4xl" title={selectedVendor.name} subtitle={`${selectedVendor.engagement_type === "main" ? "Main contractor" : selectedVendor.engagement_type === "independent" ? "Independent subcontractor" : "Subcontractor"} · ${(selectedVendor.categories || [selectedVendor.category]).join(", ")}`} onClose={() => setSelected(null)}><ContractorDetail vendor={selectedVendor} isSub={selectedVendor.engagement_type !== "main"} contacts={contactsFor(selectedVendor.id)} projects={projectsFor(selectedVendor.id)} logs={hub.logs.filter(log => log.vendor_id === selectedVendor.id)} canManage={canManage} remove={() => deleteCompany(selectedVendor)} edit={() => setForm("edit")} addContact={() => setForm("contact")} addSubcontractor={() => setForm("sub")} convertIndependent={selectedRelationship ? () => perform(() => communicationApi.unlinkSubcontractor(selectedRelationship.id), "Subcontractor converted to independent") : null} addNote={(event) => submit(event, payload => communicationApi.addLog({ ...payload, vendor_id: selectedVendor.id, project_id: payload.project_id || null, contact_id: payload.contact_id || null }), "Communication note added")}/></Modal>}</div>

    {canManage && <section className="hub-quick rounded-2xl border border-slate-200 bg-white p-5 [&>h3]:m-0 [&>h3]:font-serif [&>h3]:text-xl [&>div]:mt-4 [&>div]:grid [&>div]:grid-cols-5 [&>div]:gap-3 max-[1000px]:[&>div]:grid-cols-2 max-[520px]:[&>div]:grid-cols-1 [&_button]:grid [&_button]:gap-2 [&_button]:rounded-xl [&_button]:border [&_button]:border-slate-200 [&_button]:bg-slate-50 [&_button]:p-4 [&_button]:text-left [&_button]:text-slate-900 [&_button_span]:text-blue-700 [&_button_small]:text-slate-500"><h3>Quick actions</h3><div><QuickCard icon={<Plus/>} title="Add main contractor" text="Create a primary company" onClick={() => setForm("main")}/><QuickCard icon={<Link2/>} title="Add independent" text="Create a directly engaged subcontractor" onClick={() => setForm("independent")}/><QuickCard icon={<UserPlus/>} title="Add contact" text="Add a person to a company" onClick={() => setForm("contact")}/><QuickCard icon={<MapPinned/>} title="Map project" text="Assign main or independent contractor" onClick={() => setForm("link")}/>{canCategories && <QuickCard icon={<Plus/>} title="Add category" text="Create a reusable trade" onClick={() => setForm("category")}/>}</div></section>}

    <section className="hub-activity rounded-2xl border border-slate-200 bg-white p-5 [&>header]:flex [&>header]:items-center [&>header]:justify-between [&>header]:border-b [&>header]:border-slate-100 [&>header]:pb-4 [&>header>div]:flex [&>header>div]:items-center [&>header>div]:gap-2 [&_h3]:m-0 [&_h3]:font-serif [&_h3]:text-xl [&>div>article]:grid [&>div>article]:grid-cols-[auto_1fr] [&>div>article]:gap-3 [&>div>article]:border-b [&>div>article]:border-slate-100 [&>div>article]:py-3 [&_p]:m-0 [&_p]:text-sm [&_p]:text-slate-600 [&_small]:text-xs [&_small]:text-slate-400"><header><div><Clock3/><h3>Recent communication</h3></div><span>Manual site records</span></header><div>{hub.logs.slice(0, 5).map(log => { const vendor = vendorById[log.vendor_id]; return <article key={log.id}><span className={`activity-icon grid size-10 place-items-center rounded-xl bg-blue-50 text-blue-700 ${log.channel}`}><MessageCircle size={17}/></span><div><strong>{vendor?.name || "Contractor"}</strong><p>{log.note}</p><small>{log.created_by_name} · {new Date(log.created_at).toLocaleString()}</small></div></article>})}{!hub.logs.length && <p className="no-history py-4 text-sm text-slate-500">No communication notes have been added.</p>}</div></section>

    {form === "main" && <CompanyModal title="Add main contractor" categories={hub.categories} onClose={() => setForm(null)} onSubmit={event => createCompany(event, "main")}/>} 
    {form === "sub" && selectedVendor?.engagement_type === "main" && <CompanyModal title="Add subcontractor" categories={hub.categories} fixedMainContractor={selectedVendor} onClose={() => setForm(null)} onSubmit={event => createCompany(event, "exclusive")}/>}
    {form === "independent" && <CompanyModal title="Add independent subcontractor" categories={hub.categories} independent onClose={() => setForm(null)} onSubmit={event => createCompany(event, "independent")}/>} 
    {form === "edit" && selectedVendor && <ProfileModal vendor={selectedVendor} categories={hub.categories} onClose={() => setForm(null)} onSubmit={event => updateCompany(event, selectedVendor.id)}/>} 
    {form === "contact" && <Modal title="Add contact" subtitle="Add a contact person under a contractor" onClose={() => setForm(null)}><form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white two-col grid-cols-2 max-[720px]:grid-cols-1" onSubmit={event => submit(event, payload => communicationApi.addContact({ ...payload, is_primary: false }), "Contact added")}><label className="full-field col-span-full max-[720px]:col-span-1">Contractor<select name="vendor_id" defaultValue={selectedVendor?.id || ""} required>{hub.vendors.map(vendor => <option value={vendor.id} key={vendor.id}>{vendor.name}</option>)}</select></label><label>Name<input name="name" required/></label><label>Designation<input name="designation"/></label><label>Phone<input name="phone" required/></label><label>WhatsApp<input name="whatsapp"/></label><button>Add contact</button></form></Modal>}
    {form === "link" && <Modal title="Map contractor to project" subtitle="Make the company visible inside a project" onClose={() => setForm(null)}><form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white" onSubmit={event => submit(event, communicationApi.linkVendor, "Contractor mapped to project")}><label>Project<select name="project_id" required>{hub.projects.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label><label>Contractor<select name="vendor_id" defaultValue={selectedVendor?.id || ""} required>{hub.vendors.filter(vendor => vendor.engagement_type !== "exclusive_subcontractor").map(vendor => <option value={vendor.id} key={vendor.id}>{vendor.name}</option>)}</select></label><small>Exclusive subcontractors inherit access from their main contractor.</small><button>Map contractor</button></form></Modal>}
    {form === "category" && <Modal title="Add contractor category" subtitle="Create a standardized trade category" onClose={() => setForm(null)}><form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white" onSubmit={event => submit(event, communicationApi.addCategory, "Category added")}><label>Category name<input name="name" required/></label><button>Add category</button></form></Modal>}
    {canManage && <button className="mobile-add fixed bottom-5 right-5 z-30 grid size-14 place-items-center rounded-full bg-blue-700 p-0 text-white shadow-xl min-[721px]:hidden" aria-label="Add contractor" onClick={() => setForm("main")}><Plus/></button>}
  </div>;
}

