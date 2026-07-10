import { useState } from "react";
import { Eye, Plus } from "lucide-react";
import { ConfirmModal, ManagementHeader, ManagementTable, Modal, Pill } from "../../components/ui";
import { vendorsApi } from "../../api/vendorsApi";
import { categories } from "../../utils/constants";
import { initials } from "../../utils/format";

function VendorCreateModal({ create, onClose }) {
  return <Modal title="Add Vendor" subtitle="Create a trade contact for task assignment" onClose={onClose}><form className="modal-form two-col" onSubmit={create}><label>Vendor Company<input name="name" placeholder="Enter vendor company" required /></label><label>Work Category<select name="category">{categories.map(c => <option key={c}>{c}</option>)}</select></label><label>Contact Person<input name="contact_person" placeholder="Enter contact person" required /></label><label>Phone Number<input name="phone" placeholder="Enter phone number" required /></label><label>WhatsApp<input name="whatsapp" placeholder="Optional" /></label><label>Notes<input name="notes" placeholder="Optional" /></label><button><Plus size={18} /> Add Vendor</button></form></Modal>;
}

function VendorModal({ vendor, action, onClose }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  async function save(e) { e.preventDefault(); await action(() => vendorsApi.update(vendor.id, Object.fromEntries(new FormData(e.currentTarget))), "Vendor updated"); onClose(); }
  async function remove() { await action(() => vendorsApi.remove(vendor.id), "Vendor deleted"); setConfirmDelete(false); onClose(); }
  return <Modal title="Vendor Details" subtitle="Vendor contact and category" onClose={onClose}><div className="profile-hero"><div className="avatar large pastel">{initials(vendor.name)}</div><div><h3>{vendor.name}</h3><p>{vendor.contact_person} - {vendor.phone}</p></div><Pill>{vendor.category}</Pill></div><form className="modal-form two-col" onSubmit={save}><label>Vendor Company<input name="name" defaultValue={vendor.name} /></label><label>Category<select name="category" defaultValue={vendor.category}>{categories.map(c => <option key={c}>{c}</option>)}</select></label><label>Contact Person<input name="contact_person" defaultValue={vendor.contact_person} /></label><label>Phone<input name="phone" defaultValue={vendor.phone} /></label><label>WhatsApp<input name="whatsapp" defaultValue={vendor.whatsapp || ""} /></label><label>Notes<input name="notes" defaultValue={vendor.notes || ""} /></label><button>Save Vendor</button><button type="button" className="danger" onClick={() => setConfirmDelete(true)}>Delete Vendor</button></form>{confirmDelete && <ConfirmModal title="Delete vendor?" message={`This will remove ${vendor.name}. Assigned tasks will become unassigned.`} confirmLabel="Delete Vendor" onClose={() => setConfirmDelete(false)} onConfirm={remove} />}</Modal>;
}

export function VendorsPage({ data, action }) {
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);

  async function create(e) {
    e.preventDefault();

    const form = e.currentTarget;
    const payload = Object.fromEntries(new FormData(form));

    await action(() => vendorsApi.create(payload), "Vendor created");

    form.reset();
    setCreating(false);
  }

  return (
    <div className="stack">
      <ManagementHeader
        eyebrow="Vendor CRM"
        title="Vendors"
        subtitle="Manage vendor information and trade contacts"
        actionLabel="Add Vendor"
        actionIcon={<Plus size={18} />}
        onAction={() => setCreating(true)}
      />

      <ManagementTable
        countLabel="Total Vendors"
        count={data.vendors.length}
        searchPlaceholder="Search vendors?"
        tableClassName="vendor-table"
      >
            <colgroup>
              <col className="w-[28%]" />
              <col className="w-[15%]" />
              <col className="w-[20%]" />
              <col className="w-[15%]" />
              <col className="w-[14%]" />
              <col className="w-[8%]" />
            </colgroup>
            <thead>
              <tr className="data-row table-head">
                <th scope="col">Vendor</th>
                <th scope="col">Category</th>
                <th scope="col">Contact Person</th>
                <th scope="col">Phone</th>
                <th scope="col">Status</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.vendors.map((vendor) => (
                <tr
                  key={vendor.id}
                  className="data-row"
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelected(vendor)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") setSelected(vendor);
                  }}
                >
                  <td data-label="Vendor"><b>{vendor.name}</b><small>{vendor.notes || "Vendor contact"}</small></td>
                  <td data-label="Category">{vendor.category}</td>
                  <td data-label="Contact Person">{vendor.contact_person}</td>
                  <td data-label="Phone">{vendor.phone}</td>
                  <td data-label="Status"><Pill tone="green">Active</Pill></td>
                  <td data-label="Actions">
                    <button
                      type="button"
                      className="kebab"
                      aria-label={`Open ${vendor.name}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelected(vendor);
                      }}
                    >
                      <Eye size={20} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
      </ManagementTable>

      {creating && <VendorCreateModal create={create} onClose={() => setCreating(false)} />}
      {selected && <VendorModal vendor={selected} action={action} onClose={() => setSelected(null)} />}
    </div>
  );
}