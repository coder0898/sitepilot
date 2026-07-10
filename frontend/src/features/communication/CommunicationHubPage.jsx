import { useEffect, useMemo, useState } from "react";
import { Building2, ChevronDown, ChevronRight, Clock3, ContactRound, Filter, FolderKanban, Link2, MapPinned, MessageCircle, Pencil, Phone, Plus, Search, UserPlus, UsersRound } from "lucide-react";
import { communicationApi } from "../../api/communicationApi";
import { vendorsApi } from "../../api/vendorsApi";
import { Modal, Pill } from "../../components/ui";

const emptyHub = { vendors: [], contacts: [], categories: [], projects: [], project_vendors: [], relationships: [], logs: [] };
const cleanPhone = (value = "") => value.replace(/[^\d+]/g, "");
const statusLabel = value => ({ active: "Active", inactive: "Inactive", on_hold: "On hold" }[value] || value);

function QuickActions({ contact, compact = false }) {
  if (!contact) return <span className="no-contact">No contact</span>;
  return <div className={`contractor-actions ${compact ? "compact" : ""}`}>
    <a href={`tel:${cleanPhone(contact.phone)}`} onClick={event => event.stopPropagation()}><Phone size={16}/><span>Call</span></a>
    <a className="whatsapp" href={`https://wa.me/${cleanPhone(contact.whatsapp || contact.phone).replace("+", "")}`} target="_blank" rel="noreferrer" onClick={event => event.stopPropagation()}><MessageCircle size={16}/><span>WhatsApp</span></a>
  </div>;
}

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

  return <div className="hub-v2">
    <section className="hub-intro"><div><p>Communication Hub</p><h2>Contractors, contacts and site communication</h2><span>A mobile-first directory for every company and team working across your projects.</span></div>{canManage && <button onClick={() => setForm("main")}><Plus size={18}/> Add main contractor</button>}</section>

    <section className="hub-stat-grid"><Metric icon={<Building2/>} value={mainContractors.length} label="Main contractors" tone="blue"/><Metric icon={<UsersRound/>} value={subcontractors.length} label="Subcontractors" tone="green"/><Metric icon={<ContactRound/>} value={hub.contacts.length} label="Contacts" tone="violet"/><Metric icon={<FolderKanban/>} value={activeProjects} label="Active projects" tone="orange"/></section>

    <section className="hub-controls"><label className="hub-search"><Search size={17}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search contractor, trade or contact"/></label><button className={`filter-toggle ${showFilters ? "active" : ""}`} onClick={() => setShowFilters(value => !value)}><Filter size={17}/> Filters</button>{showFilters && <div className="hub-filters"><select value={projectId} onChange={event => setProjectId(event.target.value)}><option value="">All projects</option>{hub.projects.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}</select><select value={categoryId} onChange={event => setCategoryId(event.target.value)}><option value="">All trades</option>{hub.categories.map(category => <option value={category.id} key={category.id}>{category.name}</option>)}</select><select value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option><option value="active">Active</option><option value="on_hold">On hold</option><option value="inactive">Inactive</option></select></div>}</section>

    <div className="hub-content"><section className="hub-directory"><div className="hub-tabs"><button className={type === "all" ? "active" : ""} onClick={() => setType("all")}>All</button><button className={type === "main" ? "active" : ""} onClick={() => setType("main")}>Main contractors</button><button className={type === "sub" ? "active" : ""} onClick={() => setType("sub")}>Subcontractors</button></div>
      {type !== "sub" && visibleMains.map(main => <ContractorGroup key={main.id} main={main} children={childrenFor(main.id).filter(({ vendor }) => matches(vendor) && projectMatches(vendor))} primaryFor={primaryFor} isOpen={expanded.has(main.id)} toggle={toggle} select={setSelected} showChildren={type === "all"}/>) }
      {type === "sub" && visibleSubs.map(sub => <FlatContractor key={sub.id} vendor={sub} primary={primaryFor(sub.id)} select={setSelected} />)}
      {((type === "sub" && !visibleSubs.length) || (type !== "sub" && !visibleMains.length)) && <div className="comm-empty">No contractors match these filters.</div>}
    </section>{selectedVendor && <Modal className="contractor-detail-modal" title={selectedVendor.name} subtitle={`${selectedVendor.engagement_type === "main" ? "Main contractor" : selectedVendor.engagement_type === "independent" ? "Independent subcontractor" : "Subcontractor"} · ${(selectedVendor.categories || [selectedVendor.category]).join(", ")}`} onClose={() => setSelected(null)}><ContractorDetail vendor={selectedVendor} isSub={selectedVendor.engagement_type !== "main"} contacts={contactsFor(selectedVendor.id)} projects={projectsFor(selectedVendor.id)} logs={hub.logs.filter(log => log.vendor_id === selectedVendor.id)} canManage={canManage} edit={() => setForm("edit")} addContact={() => setForm("contact")} addSubcontractor={() => setForm("sub")} convertIndependent={selectedRelationship ? () => perform(() => communicationApi.unlinkSubcontractor(selectedRelationship.id), "Subcontractor converted to independent") : null} addNote={(event) => submit(event, payload => communicationApi.addLog({ ...payload, vendor_id: selectedVendor.id, project_id: payload.project_id || null, contact_id: payload.contact_id || null }), "Communication note added")}/></Modal>}</div>

    {canManage && <section className="hub-quick"><h3>Quick actions</h3><div><QuickCard icon={<Plus/>} title="Add main contractor" text="Create a primary company" onClick={() => setForm("main")}/><QuickCard icon={<Link2/>} title="Add independent" text="Create a directly engaged subcontractor" onClick={() => setForm("independent")}/><QuickCard icon={<UserPlus/>} title="Add contact" text="Add a person to a company" onClick={() => setForm("contact")}/><QuickCard icon={<MapPinned/>} title="Map project" text="Assign main or independent contractor" onClick={() => setForm("link")}/>{canCategories && <QuickCard icon={<Plus/>} title="Add category" text="Create a reusable trade" onClick={() => setForm("category")}/>}</div></section>}

    <section className="hub-activity"><header><div><Clock3/><h3>Recent communication</h3></div><span>Manual site records</span></header><div>{hub.logs.slice(0, 5).map(log => { const vendor = vendorById[log.vendor_id]; return <article key={log.id}><span className={`activity-icon ${log.channel}`}><MessageCircle size={17}/></span><div><strong>{vendor?.name || "Contractor"}</strong><p>{log.note}</p><small>{log.created_by_name} · {new Date(log.created_at).toLocaleString()}</small></div></article>})}{!hub.logs.length && <p className="no-history">No communication notes have been added.</p>}</div></section>

    {form === "main" && <CompanyModal title="Add main contractor" categories={hub.categories} onClose={() => setForm(null)} onSubmit={event => createCompany(event, "main")}/>} 
    {form === "sub" && selectedVendor?.engagement_type === "main" && <CompanyModal title="Add subcontractor" categories={hub.categories} fixedMainContractor={selectedVendor} onClose={() => setForm(null)} onSubmit={event => createCompany(event, "exclusive")}/>}
    {form === "independent" && <CompanyModal title="Add independent subcontractor" categories={hub.categories} independent onClose={() => setForm(null)} onSubmit={event => createCompany(event, "independent")}/>} 
    {form === "edit" && selectedVendor && <ProfileModal vendor={selectedVendor} categories={hub.categories} onClose={() => setForm(null)} onSubmit={event => updateCompany(event, selectedVendor.id)}/>} 
    {form === "contact" && <Modal title="Add contact" subtitle="Add a contact person under a contractor" onClose={() => setForm(null)}><form className="modal-form two-col" onSubmit={event => submit(event, payload => communicationApi.addContact({ ...payload, is_primary: false }), "Contact added")}><label className="full-field">Contractor<select name="vendor_id" defaultValue={selectedVendor?.id || ""} required>{hub.vendors.map(vendor => <option value={vendor.id} key={vendor.id}>{vendor.name}</option>)}</select></label><label>Name<input name="name" required/></label><label>Designation<input name="designation"/></label><label>Phone<input name="phone" required/></label><label>WhatsApp<input name="whatsapp"/></label><button>Add contact</button></form></Modal>}
    {form === "link" && <Modal title="Map contractor to project" subtitle="Make the company visible inside a project" onClose={() => setForm(null)}><form className="modal-form" onSubmit={event => submit(event, communicationApi.linkVendor, "Contractor mapped to project")}><label>Project<select name="project_id" required>{hub.projects.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label><label>Contractor<select name="vendor_id" defaultValue={selectedVendor?.id || ""} required>{hub.vendors.filter(vendor => vendor.engagement_type !== "exclusive_subcontractor").map(vendor => <option value={vendor.id} key={vendor.id}>{vendor.name}</option>)}</select></label><small>Exclusive subcontractors inherit access from their main contractor.</small><button>Map contractor</button></form></Modal>}
    {form === "category" && <Modal title="Add contractor category" subtitle="Create a standardized trade category" onClose={() => setForm(null)}><form className="modal-form" onSubmit={event => submit(event, communicationApi.addCategory, "Category added")}><label>Category name<input name="name" required/></label><button>Add category</button></form></Modal>}
    {canManage && <button className="mobile-add" aria-label="Add contractor" onClick={() => setForm("main")}><Plus/></button>}
  </div>;
}

function Metric({ icon, value, label, tone }) { return <article className={`hub-metric ${tone}`}><span>{icon}</span><strong>{value}</strong><small>{label}</small></article>; }
function QuickCard({ icon, title, text, onClick }) { return <button onClick={onClick}><span>{icon}</span><strong>{title}</strong><small>{text}</small></button>; }
function CategoryPills({ vendor }) { return <div className="category-pills">{(vendor.categories || [vendor.category]).slice(0, 3).map(category => <Pill key={category}>{category}</Pill>)}</div>; }

function ContractorGroup({ main, children, primaryFor, isOpen, toggle, select, showChildren }) {
  return <article className="directory-group"><div className="directory-row main-row" onClick={() => select(main.id)}><button className="row-expand" onClick={event => { event.stopPropagation(); toggle(main.id); }}>{isOpen ? <ChevronDown/> : <ChevronRight/>}</button><div className="company-avatar">{main.name.slice(0,2).toUpperCase()}</div><div className="row-company"><div><h3>{main.name}</h3><Pill tone="blue">Main contractor</Pill><Pill tone={main.status === "active" ? "green" : "orange"}>{statusLabel(main.status)}</Pill></div><CategoryPills vendor={main}/><small>{children.length} subcontractor{children.length === 1 ? "" : "s"} · {primaryFor(main.id)?.name || "No primary contact"}</small></div><QuickActions contact={primaryFor(main.id)} compact/></div>{showChildren && isOpen && <div className="nested-companies">{children.map(({ relation, vendor }) => <div className="directory-row sub-row" key={relation.id} onClick={() => select(vendor.id)}><span className="branch"><Link2/></span><div className="company-avatar sub">{vendor.name.slice(0,2).toUpperCase()}</div><div className="row-company"><div><h4>{vendor.name}</h4><Pill tone="green">{vendor.engagement_type === "independent" ? "Independent" : "Subcontractor"}</Pill><Pill tone={vendor.status === "active" ? "green" : "orange"}>{statusLabel(vendor.status)}</Pill></div><CategoryPills vendor={vendor}/><small>{primaryFor(vendor.id)?.name || "No primary contact"}</small></div><QuickActions contact={primaryFor(vendor.id)} compact/></div>)}{!children.length && <p className="empty-nested">No linked subcontractors.</p>}</div>}</article>;
}function FlatContractor({ vendor, primary, select }) { return <article className="directory-group"><div className="directory-row main-row flat" onClick={() => select(vendor.id)}><div className="company-avatar sub">{vendor.name.slice(0,2).toUpperCase()}</div><div className="row-company"><div><h3>{vendor.name}</h3><Pill tone="green">{vendor.engagement_type === "independent" ? "Independent" : "Subcontractor"}</Pill><Pill tone={vendor.status === "active" ? "green" : "orange"}>{statusLabel(vendor.status)}</Pill></div><CategoryPills vendor={vendor}/><small>{primary?.name || "No primary contact"}</small></div><QuickActions contact={primary} compact/></div></article>; }

function ContractorDetail({ vendor, isSub, contacts, projects, logs, canManage, edit, addContact, addSubcontractor, convertIndependent, addNote }) {
  const primary = contacts.find(contact => contact.is_primary) || contacts[0];
  return <div className="contractor-detail-content"><div className="detail-company-hero"><div className="company-avatar large-detail">{vendor.name.slice(0,2).toUpperCase()}</div><div><div className="inspector-badges"><Pill tone={isSub ? "green" : "blue"}>{vendor.engagement_type === "independent" ? "Independent" : isSub ? "Subcontractor" : "Main contractor"}</Pill><Pill tone={vendor.status === "active" ? "green" : "orange"}>{statusLabel(vendor.status)}</Pill></div><p>{vendor.notes || "No company notes added."}</p></div><QuickActions contact={primary}/></div><div className="detail-modal-grid"><section><h4>Company details</h4><dl><div><dt>Trade categories</dt><dd>{vendor.categories?.join(", ") || vendor.category}</dd></div><div><dt>Engagement</dt><dd>{vendor.engagement_type === "exclusive_subcontractor" ? "Under main contractor" : vendor.engagement_type === "independent" ? "Direct / independent" : "Main contractor"}</dd></div><div><dt>GST number</dt><dd>{vendor.gst_number || "Not provided"}</dd></div><div><dt>Email</dt><dd>{vendor.email || "Not provided"}</dd></div><div><dt>Address</dt><dd>{vendor.address || "Not provided"}</dd></div></dl></section><section><div className="section-title"><h4>Key contacts</h4>{canManage && <button onClick={addContact}>+ Add contact</button>}</div>{contacts.map(contact => <article className="inspector-contact" key={contact.id}><div><strong>{contact.name}</strong><span>{contact.designation || "Contact person"}</span><small>{contact.phone}</small></div><QuickActions contact={contact} compact/></article>)}{!contacts.length && <p className="no-history">No contacts added.</p>}</section><section><h4>Assigned projects</h4>{projects.map(project => <article className="inspector-project" key={project.id}><div><strong>{project.name}</strong><span>{vendor.engagement_type === "exclusive_subcontractor" ? "Inherited from main contractor" : statusLabel(project.status)}</span></div><Pill tone="green">{statusLabel(project.status)}</Pill></article>)}{!projects.length && <p className="no-history">Not mapped to a project.</p>}</section><section className="detail-notes"><h4>Communication notes</h4><div className="detail-log-list">{logs.slice(0,4).map(log => <article className="inspector-log" key={log.id}><strong>{log.channel.replace("_", " ")}</strong><p>{log.note}</p><small>{new Date(log.created_at).toLocaleString()}</small></article>)}{!logs.length && <p className="no-history">No communication notes yet.</p>}</div><form className="inspector-note" onSubmit={addNote}><select name="project_id"><option value="">General</option>{projects.map(project => <option value={project.id} key={project.id}>{project.name}</option>)}</select><select name="contact_id"><option value="">Company</option>{contacts.map(contact => <option value={contact.id} key={contact.id}>{contact.name}</option>)}</select><input type="hidden" name="channel" value="note"/><textarea name="note" required placeholder="What was discussed or needs follow-up?"/><button>Add communication note</button></form></section></div>{canManage && <div className="detail-modal-footer">{vendor.engagement_type === "main" && <button className="secondary-button detail-secondary" onClick={addSubcontractor}><Plus/> Add subcontractor</button>}{convertIndependent && <button className="secondary-button detail-secondary" onClick={convertIndependent}><Link2/> Convert to independent</button>}<button className="edit-contractor" onClick={edit}><Pencil/> Edit contractor</button></div>}</div>;
}
function CategoryChoices({ categories, selected = [] }) { return <fieldset className="category-choices"><legend>Trade categories</legend><div>{categories.map(category => <label key={category.id} className={selected.includes(category.id) ? "checked" : ""}><input type="checkbox" name="category_ids" value={category.id} defaultChecked={selected.includes(category.id)}/><span>{category.name}</span></label>)}</div><small>Select one or more trades.</small></fieldset>; }
function CompanyModal({ title, categories, fixedMainContractor, independent, onClose, onSubmit }) { return <Modal title={title} subtitle={fixedMainContractor ? `Automatically linked under ${fixedMainContractor.name}` : independent ? "Directly engaged and available for project mapping" : "Add company, trade and primary contact information"} onClose={onClose}><form className="modal-form two-col contractor-form" onSubmit={onSubmit}>{fixedMainContractor && <div className="fixed-main full-field"><span>Under main contractor</span><strong>{fixedMainContractor.name}</strong><input type="hidden" name="main_contractor_id" value={fixedMainContractor.id}/></div>}<label>Company name<input name="name" required/></label><label>Status<select name="status"><option value="active">Active</option><option value="on_hold">On hold</option><option value="inactive">Inactive</option></select></label><CategoryChoices categories={categories}/><label>Primary contact<input name="contact_person" required/></label><label>Designation<input name="designation"/></label><label>Phone<input name="phone" required/></label><label>WhatsApp<input name="whatsapp"/></label><label>Email<input name="email" type="email"/></label><label>GST number<input name="gst_number"/></label><label className="full-field">Address<textarea name="address"/></label><label className="full-field">Notes<input name="notes"/></label><button>{title}</button></form></Modal>; }function ProfileModal({ vendor, categories, onClose, onSubmit }) { return <Modal title={`Edit ${vendor.name}`} subtitle="Update company profile, status and trades" onClose={onClose}><form className="modal-form two-col contractor-form" onSubmit={onSubmit}><label>Company name<input name="name" defaultValue={vendor.name} required/></label><label>Status<select name="status" defaultValue={vendor.status}><option value="active">Active</option><option value="on_hold">On hold</option><option value="inactive">Inactive</option></select></label><CategoryChoices categories={categories} selected={vendor.category_ids}/><label>Email<input name="email" type="email" defaultValue={vendor.email || ""}/></label><label>GST number<input name="gst_number" defaultValue={vendor.gst_number || ""}/></label><label className="full-field">Address<textarea name="address" defaultValue={vendor.address || ""}/></label><label className="full-field">Notes<input name="notes" defaultValue={vendor.notes || ""}/></label><button>Save contractor</button></form></Modal>; }