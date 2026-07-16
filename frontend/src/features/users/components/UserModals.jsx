import { useState } from "react";
import { KeyRound, Save, UserPlus } from "lucide-react";
import { usersApi } from "../../../api/usersApi";
import { Button, ConfirmModal, DetailGrid, Field, FormActions, FormGrid, Input, Modal, Pill, Select } from "../../../components/ui";
import { roles } from "../../../utils/constants";
import { initials } from "../../../utils/format";

function roleOptionsFor(actorRole, currentRole = "") {
  const options = actorRole === "super_admin" ? ["admin", "project_manager", "supervisor"] : ["project_manager", "supervisor"];
  return Array.from(new Set([currentRole, ...options].filter(Boolean)));
}

export function CreateUserModal({ create, user, onClose }) {
  return <Modal title="Create user" subtitle="Create a secure, role-based SiteOps login" onClose={onClose}><form className="grid gap-5" onSubmit={create}><FormGrid><Field label="Full name"><Input name="name" autoComplete="name" placeholder="Enter full name" required/></Field><Field label="Email login"><Input name="email" type="email" autoComplete="email" placeholder="Enter email address" required/></Field><Field label="Mobile number" hint="Used for site contact and future WhatsApp messaging"><Input name="phone" inputMode="tel" placeholder="Enter mobile number"/></Field><Field label="Temporary password"><Input name="password" type="password" autoComplete="new-password" placeholder="Enter temporary password" required/></Field><Field label="Role" className="md:col-span-2"><Select name="role" defaultValue="" required><option value="" disabled>Select role</option>{roleOptionsFor(user.role).map(role => <option key={role} value={role}>{roles[role]}</option>)}</Select></Field></FormGrid><FormActions><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit"><UserPlus size={18}/>Create user</Button></FormActions></form></Modal>;
}

export function UserModal({ selectedUser, currentUser, onClose, action }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState(null);
  const protectedUser = selectedUser.role === "super_admin";

  async function save(event) { event.preventDefault(); const result = await action(() => usersApi.update(selectedUser.id, Object.fromEntries(new FormData(event.currentTarget))), "User updated"); if (result?.ok !== false) onClose(); }
  async function toggleActive() { const result = await action(() => usersApi.setActive(selectedUser.id, !selectedUser.active), "User status updated"); if (result?.ok !== false) onClose(); }
  async function resetPassword() { const result = await action(() => usersApi.resetPassword(selectedUser.id, password), "Password reset"); if (result?.ok !== false) setPassword(""); }

  return <Modal title="User details" subtitle="Identity, access and account status" onClose={onClose}>
    <div className="mb-5 flex items-center gap-4 rounded-2xl bg-slate-950 p-4 text-white sm:p-5"><div className="grid size-12 shrink-0 place-items-center rounded-2xl bg-blue-600 font-black">{initials(selectedUser.name)}</div><div className="min-w-0 flex-1"><h3 className="truncate text-lg font-black">{selectedUser.name}</h3><p className="truncate text-sm text-slate-300">{selectedUser.email}</p></div><Pill tone={selectedUser.active ? "green" : "gray"}>{selectedUser.active ? "Active" : "Inactive"}</Pill></div>
    <DetailGrid className="mb-5" items={[{ label: "Role", value: roles[selectedUser.role] }, { label: "Status", value: selectedUser.active ? "Active" : "Inactive" }, { label: "Created", value: selectedUser.created_at ? new Date(selectedUser.created_at).toLocaleDateString("en-GB") : "-" }, { label: "Last login", value: selectedUser.last_login_at ? new Date(selectedUser.last_login_at).toLocaleString("en-GB") : "Not yet" }]}/>
    {protectedUser ? <div className="rounded-2xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm font-bold text-blue-900">System owner account. Protected from role and status changes.</div> : <form className="grid gap-5" onSubmit={save}><FormGrid><Field label="Full name"><Input name="name" defaultValue={selectedUser.name} required/></Field><Field label="Email login"><Input name="email" type="email" defaultValue={selectedUser.email} required/></Field><Field label="Mobile number"><Input name="phone" inputMode="tel" defaultValue={selectedUser.phone || ""}/></Field><Field label="Role"><Select name="role" defaultValue={selectedUser.role}>{roleOptionsFor(currentUser.role, selectedUser.role).map(role => <option key={role} value={role}>{roles[role]}</option>)}</Select></Field></FormGrid><div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"><Field label="Set a new password"><Input type="password" value={password} onChange={event => setPassword(event.target.value)} placeholder="New password"/></Field><Button type="button" variant="secondary" disabled={!password} onClick={resetPassword}><KeyRound size={17}/>Reset</Button></div><FormActions className="border-t border-slate-100 pt-4"><Button type="button" variant={selectedUser.active ? "danger" : "secondary"} onClick={() => setConfirm("status")}>{selectedUser.active ? "Deactivate" : "Activate"}</Button><Button type="submit"><Save size={17}/>Save user</Button></FormActions></form>}
    {confirm === "status" && <ConfirmModal title={selectedUser.active ? "Deactivate user?" : "Activate user?"} message={`This will ${selectedUser.active ? "block" : "restore"} login access for ${selectedUser.name}.`} confirmLabel={selectedUser.active ? "Deactivate" : "Activate"} onClose={() => setConfirm(null)} onConfirm={toggleActive}/>}
  </Modal>;
}
