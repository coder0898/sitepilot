import { useState } from "react";
import { MoreVertical, Plus } from "lucide-react";
import { ManagementHeader, ManagementTable, Modal, Pill } from "../../components/ui";
import { vendorsApi } from "../../api/vendorsApi";
import { categories } from "../../utils/constants";
import { initials } from "../../utils/format";

function VendorCreateModal({ create, onClose }) {
  return <Modal title="Add Vendor" subtitle="Create a trade contact for task assignment" onClose={onClose}><form className="modal-form two-col" onSubmit={create}><label>Vendor Company<input name="name" placeholder="Enter vendor company" required /></label><label>Work Category<select name="category">{categories.map(c => <option key={c}>{c}</option>)}</select></label><label>Contact Person<input name="contact_person" placeholder="Enter contact person" required /></label><label>Phone Number<input name="phone" placeholder="Enter phone number" required /></label><label>WhatsApp<input name="whatsapp" placeholder="Optional" /></label><label>Notes<input name="notes" placeholder="Optional" /></label><button><Plus size={18} /> Add Vendor</button></form></Modal>;
}

function VendorModal({ vendor, action, onClose }) {
  async function save(e) { e.preventDefault(); await action(() => vendorsApi.update(vendor.id, Object.fromEntries(new FormData(e.currentTarget))), "Vendor updated"); onClose(); }
  async function remove() { if (confirm("Delete this vendor?")) { await action(() => vendorsApi.remove(vendor.id), "Vendor deleted"); onClose(); } }
  return <Modal title="Vendor Details" subtitle="Vendor contact and category" onClose={onClose}><div className="profile-hero"><div className="avatar large pastel">{initials(vendor.name)}</div><div><h3>{vendor.name}</h3><p>{vendor.contact_person} • {vendor.phone}</p></div><Pill>{vendor.category}</Pill></div><form className="modal-form two-col" onSubmit={save}><label>Vendor Company<input name="name" defaultValue={vendor.name} /></label><label>Category<select name="category" defaultValue={vendor.category}>{categories.map(c => <option key={c}>{c}</option>)}</select></label><label>Contact Person<input name="contact_person" defaultValue={vendor.contact_person} /></label><label>Phone<input name="phone" defaultValue={vendor.phone} /></label><label>WhatsApp<input name="whatsapp" defaultValue={vendor.whatsapp || ""} /></label><label>Notes<input name="notes" defaultValue={vendor.notes || ""} /></label><button>Save Vendor</button><button type="button" className="danger" onClick={remove}>Delete Vendor</button></form></Modal>;
}

export function VendorsPage({ data, action }) {
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);
  async function create(e) { e.preventDefault(); const form = e.currentTarget; const payload = Object.fromEntries(new FormData(form)); await action(() => vendorsApi.create(payload), "Vendor created"); form.reset(); setCreating(false); }
  return <div className="stack"><ManagementHeader eyebrow="Vendor CRM" title="Vendors" subtitle="Manage vendor information and trade contacts" actionLabel="Add Vendor" actionIcon={<Plus size={18} />} onAction={() => setCreating(true)} /><ManagementTable countLabel="Total Vendors" count={data.vendors.length} searchPlaceholder="Search vendors?"><div className="data-table vendor-table"><div className="data-row table-head"><span>Vendor</span><span>Category</span><span>Contact Person</span><span>Phone</span><span>Status</span><span>Actions</span></div>{data.vendors.map(v => <button className="data-row" key={v.id} onClick={() => setSelected(v)}><span><b>{v.name}</b><small>{v.notes || "Vendor contact"}</small></span><span>{v.category}</span><span>{v.contact_person}</span><span>{v.phone}</span><span><Pill tone="green">Active</Pill></span><span><span className="kebab"><MoreVertical size={20} /></span></span></button>)}</div></ManagementTable>{creating && <VendorCreateModal create={create} onClose={() => setCreating(false)} />}{selected && <VendorModal vendor={selected} action={action} onClose={() => setSelected(null)} />}</div>;
}
