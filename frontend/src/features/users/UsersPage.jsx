import { useState } from "react";
import { UserPlus } from "lucide-react";
import { ConfirmModal, ManagementHeader, ManagementTable, Modal, Pill } from "../../components/ui";
import { usersApi } from "../../api/usersApi";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";

function roleOptionsFor(actorRole, currentRole = "") {
  const options = actorRole === "super_admin"
    ? ["admin", "project_manager", "supervisor"]
    : ["project_manager", "supervisor"];
  return Array.from(new Set([currentRole, ...options].filter(Boolean)));
}

function CreateUserModal({ create, user, onClose }) {
  return <Modal title="Create User" subtitle="Create a role-based login" onClose={onClose}>
    <form className="modal-form two-col" onSubmit={create}>
      <label>Full Name<input name="name" placeholder="Enter full name" required /></label>
      <label>Email Login<input name="email" placeholder="Enter email address" required /></label><label>Mobile Number<input name="phone" placeholder="Required for task notifications" /></label>
      <label>Temporary Password<input name="password" type="password" placeholder="Enter temporary password" required /></label>
      <label>Role<select name="role" defaultValue="" required><option value="" disabled>Select role</option>{roleOptionsFor(user.role).map(role => <option key={role} value={role}>{roles[role]}</option>)}</select></label>
      <button><UserPlus size={18} /> Create User</button>
    </form>
  </Modal>;
}

function UserModal({ selectedUser, currentUser, onClose, action }) {
  const [pwd, setPwd] = useState("");
  const [confirm, setConfirm] = useState(null);
  const protectedUser = selectedUser.role === "super_admin";
  const editable = !protectedUser;

  async function save(e) {
    e.preventDefault();
    await action(() => usersApi.update(selectedUser.id, Object.fromEntries(new FormData(e.currentTarget))), "User updated");
    onClose();
  }

  async function removeUser() {
    await action(() => usersApi.remove(selectedUser.id), "User deleted");
    setConfirm(null);
    onClose();
  }

  async function toggleActive() {
    await action(() => usersApi.setActive(selectedUser.id, !selectedUser.active), "User status updated");
    setConfirm(null);
    onClose();
  }

  return <Modal title="User Details" subtitle="View and manage user access" onClose={onClose}>
    <div className="profile-hero"><div className="avatar large pastel">{initials(selectedUser.name)}</div><div><h3>{selectedUser.name}</h3><p>{selectedUser.email}</p></div><Pill tone={selectedUser.active ? "green" : "gray"}>{selectedUser.active ? "Active" : "Inactive"}</Pill></div>
    <div className="detail-grid"><article><span>Role</span><strong>{roles[selectedUser.role]}</strong></article><article><span>Status</span><strong>{selectedUser.active ? "Active" : "Inactive"}</strong></article><article><span>Created</span><strong>{selectedUser.created_at ? new Date(selectedUser.created_at).toLocaleDateString("en-GB") : "-"}</strong></article><article><span>Last Login</span><strong>{selectedUser.last_login_at ? new Date(selectedUser.last_login_at).toLocaleString("en-GB") : "Not yet"}</strong></article></div>
    {protectedUser ? <div className="info-strip">System owner account. Protected from changes.</div> : <form className="modal-form two-col" onSubmit={save}>
      <label>Full Name<input name="name" defaultValue={selectedUser.name} required /></label>
      <label>Email Login<input name="email" defaultValue={selectedUser.email} required /></label><label>Mobile Number<input name="phone" defaultValue={selectedUser.phone || ""} /></label>
      <label>Role<select name="role" defaultValue={selectedUser.role}>{roleOptionsFor(currentUser.role, selectedUser.role).map(role => <option key={role} value={role}>{roles[role]}</option>)}</select></label>
      <label>Status<input value={selectedUser.active ? "Active" : "Inactive"} readOnly /></label>
      <div className="wide grid grid-cols-1 gap-3 md:grid-cols-2">
        <button type="submit" className="min-h-[52px] w-full rounded-[9px] bg-[#0b5bd3] px-5 font-black text-white shadow-none transition hover:-translate-y-0.5 hover:shadow-[0_16px_30px_rgba(11,91,211,0.18)]">Save User</button>
        <button type="button" className={`min-h-[52px] w-full rounded-[9px] px-5 font-black transition hover:-translate-y-0.5 ${selectedUser.active ? "border border-rose-200 bg-rose-50 text-rose-700" : "bg-[#0b5bd3] text-white"}`} onClick={() => setConfirm("status")}>{selectedUser.active ? "Deactivate User" : "Activate User"}</button>
      </div>
      <div className="wide grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_180px] md:items-end">
        <label className="grid gap-2 text-sm font-extrabold text-[#1c2d46]">New Password<input type="password" value={pwd} onChange={e => setPwd(e.target.value)} placeholder="New password" /></label>
        <button type="button" className="min-h-[52px] w-full rounded-[9px] bg-[#0b5bd3] px-5 font-black text-white disabled:cursor-not-allowed disabled:opacity-50" disabled={!pwd} onClick={() => action(() => usersApi.resetPassword(selectedUser.id, pwd), "Password reset")}>Reset Password</button>
      </div>
    </form>}
    {confirm === "delete" && <ConfirmModal title="Delete user permanently?" message={`Delete ${selectedUser.name}. This is only allowed after their projects and tasks are reassigned.`} confirmLabel="Delete User" onClose={() => setConfirm(null)} onConfirm={removeUser} />}
    {confirm === "status" && <ConfirmModal title={selectedUser.active ? "Deactivate user?" : "Activate user?"} message={`This will ${selectedUser.active ? "block" : "restore"} login access for ${selectedUser.name}.`} confirmLabel={selectedUser.active ? "Deactivate" : "Activate"} onClose={() => setConfirm(null)} onConfirm={toggleActive} />}
  </Modal>;
}

export function UsersPage({ data, user, action }) {
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);

  async function create(e) {
    e.preventDefault();

    const form = e.currentTarget;
    const payload = Object.fromEntries(new FormData(form));

    await action(() => usersApi.create(payload), "User created");

    form.reset();
    setCreating(false);
  }

  return (
    <div className="stack">
      <ManagementHeader
        eyebrow="Access control"
        title="Users"
        subtitle="Manage team access and permissions"
        actionLabel="Create User"
        actionIcon={<UserPlus size={18} />}
        onAction={() => setCreating(true)}
      />

      <ManagementTable
        countLabel="Total Users"
        count={data.users.length}
        searchPlaceholder="Search users"
        tableClassName="user-directory-table min-w-[920px] table-fixed"
      >
        <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
          <tr>
            <th className="w-[21%] px-5 py-4">User</th><th className="w-[24%] px-5 py-4">Email</th><th className="w-[14%] px-5 py-4">Role</th><th className="w-[11%] px-5 py-4">Status</th><th className="w-[13%] px-5 py-4">Created</th><th className="w-[12%] px-5 py-4">Last login</th><th className="w-[72px] px-3 py-4 text-center">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data.users.map(item => <tr key={item.id} className="cursor-pointer transition hover:bg-blue-50/50" onClick={() => setSelected(item)}>
            <td className="px-5 py-4"><span className="flex min-w-0 items-center gap-3"><span className="avatar pastel shrink-0">{initials(item.name)}</span><b className="truncate">{item.name}</b></span></td>
            <td className="truncate px-5 py-4 font-bold text-slate-700">{item.email}</td><td className="px-5 py-4"><Pill>{roles[item.role]}</Pill></td><td className="px-5 py-4"><Pill tone={item.active ? "green" : "gray"}>{item.active ? "Active" : "Inactive"}</Pill></td>
            <td className="px-5 py-4 text-slate-600">{item.created_at ? new Date(item.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "-"}</td><td className="px-5 py-4 text-slate-600">{item.last_login_at ? new Date(item.last_login_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "Not yet"}</td>
            <td className="px-3 py-4 text-center"><button type="button" className="user-action-button" aria-label={`View or edit ${item.name}`} title="View user" onClick={event => { event.stopPropagation(); setSelected(item); }}><span aria-hidden="true">→</span></button></td>
          </tr>)}
        </tbody>
      </ManagementTable>

      {creating && <CreateUserModal create={create} user={user} onClose={() => setCreating(false)} />}
      {selected && <UserModal selectedUser={selected} currentUser={user} onClose={() => setSelected(null)} action={action} />}
    </div>
  );
}


