import { useState } from "react";
import { UserPlus } from "lucide-react";
import { usersApi } from "../../../api/usersApi";
import { Button, ConfirmModal, Field, Input, Modal, Pill, Select } from "../../../components/ui";
import { roles } from "../../../utils/constants";
import { initials } from "../../../utils/format";

function roleOptionsFor(actorRole, currentRole = "") {
  const options = actorRole === "super_admin"
    ? ["admin", "project_manager", "supervisor"]
    : ["project_manager", "supervisor"];
  return Array.from(new Set([currentRole, ...options].filter(Boolean)));
}

export function CreateUserModal({ create, user, onClose }) {
  return (
    <Modal title="Create User" subtitle="Create a role-based login" onClose={onClose}>
      <form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white two-col grid-cols-2 max-[720px]:grid-cols-1" onSubmit={create}>
        <Field label="Full Name"><Input name="name" placeholder="Enter full name" required /></Field>
        <Field label="Email Login"><Input name="email" type="email" placeholder="Enter email address" required /></Field>
        <Field label="Mobile Number"><Input name="phone" placeholder="Required for task notifications" /></Field>
        <Field label="Temporary Password"><Input name="password" type="password" placeholder="Enter temporary password" required /></Field>
        <Field label="Role"><Select name="role" defaultValue="" required><option value="" disabled>Select role</option>{roleOptionsFor(user.role).map(role => <option key={role} value={role}>{roles[role]}</option>)}</Select></Field>
        <Button type="submit"><UserPlus size={18} /> Create User</Button>
      </form>
    </Modal>
  );
}

export function UserModal({ selectedUser, currentUser, onClose, action }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState(null);
  const protectedUser = selectedUser.role === "super_admin";

  async function save(event) {
    event.preventDefault();
    await action(() => usersApi.update(selectedUser.id, Object.fromEntries(new FormData(event.currentTarget))), "User updated");
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

  return (
    <Modal title="User Details" subtitle="View and manage user access" onClose={onClose}>
      <div className="profile-hero mb-4 grid grid-cols-[auto_1fr_auto] items-center gap-4 rounded-2xl border border-blue-100 bg-gradient-to-br from-slate-50 to-blue-50 p-5 max-[620px]:grid-cols-[auto_1fr] [&_h3]:m-0 [&_h3]:text-2xl [&_h3]:font-black [&_p]:m-0 [&_p]:text-slate-500">
        <div className="avatar grid size-[46px] shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-blue-900 font-black text-white shadow-[0_12px_24px_rgba(11,91,211,0.22)] large pastel">{initials(selectedUser.name)}</div>
        <div><h3>{selectedUser.name}</h3><p>{selectedUser.email}</p></div>
        <Pill tone={selectedUser.active ? "green" : "gray"}>{selectedUser.active ? "Active" : "Inactive"}</Pill>
      </div>
      <div className="detail-grid my-4 grid grid-cols-2 gap-3 max-[620px]:grid-cols-1 [&>article]:min-w-0 [&>article]:rounded-2xl [&>article]:border [&>article]:border-slate-200 [&>article]:bg-white [&>article]:p-4 [&_span]:mb-2 [&_span]:block [&_span]:text-xs [&_span]:font-black [&_span]:uppercase [&_span]:tracking-wider [&_span]:text-slate-500 [&_strong]:block [&_strong]:break-words">
        <article><span>Role</span><strong>{roles[selectedUser.role]}</strong></article>
        <article><span>Status</span><strong>{selectedUser.active ? "Active" : "Inactive"}</strong></article>
        <article><span>Created</span><strong>{selectedUser.created_at ? new Date(selectedUser.created_at).toLocaleDateString("en-GB") : "-"}</strong></article>
        <article><span>Last Login</span><strong>{selectedUser.last_login_at ? new Date(selectedUser.last_login_at).toLocaleString("en-GB") : "Not yet"}</strong></article>
      </div>
      {protectedUser ? <div className="info-strip rounded-2xl bg-blue-50 px-4 py-3 font-bold text-blue-800">System owner account. Protected from changes.</div> : (
        <form className="modal-form grid gap-3 [&_label]:grid [&_label]:gap-2 [&_label]:text-sm [&_label]:font-extrabold [&_label]:text-slate-700 [&_input]:min-h-11 [&_input]:w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-slate-200 [&_input]:bg-white [&_input]:px-4 [&_input]:py-3 [&_input]:outline-none [&_select]:min-h-11 [&_select]:w-full [&_select]:rounded-xl [&_select]:border [&_select]:border-slate-200 [&_select]:bg-white [&_select]:px-4 [&_select]:py-3 [&_select]:outline-none [&_textarea]:min-h-24 [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-xl [&_textarea]:border [&_textarea]:border-slate-200 [&_textarea]:bg-white [&_textarea]:px-4 [&_textarea]:py-3 [&_textarea]:outline-none focus-within:[&_input]:border-blue-600 focus-within:[&_select]:border-blue-600 focus-within:[&_textarea]:border-blue-600 [&>button]:min-h-12 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:font-black [&>button]:text-white two-col grid-cols-2 max-[720px]:grid-cols-1" onSubmit={save}>
          <Field label="Full Name"><Input name="name" defaultValue={selectedUser.name} required /></Field>
          <Field label="Email Login"><Input name="email" type="email" defaultValue={selectedUser.email} required /></Field>
          <Field label="Mobile Number"><Input name="phone" defaultValue={selectedUser.phone || ""} /></Field>
          <Field label="Role"><Select name="role" defaultValue={selectedUser.role}>{roleOptionsFor(currentUser.role, selectedUser.role).map(role => <option key={role} value={role}>{roles[role]}</option>)}</Select></Field>
          <Field label="Status"><Input value={selectedUser.active ? "Active" : "Inactive"} readOnly /></Field>
          <div className="wide col-span-full grid grid-cols-1 gap-3 md:grid-cols-2">
            <Button type="submit" className="min-h-[52px] w-full">Save User</Button>
            <Button type="button" className="min-h-[52px] w-full" variant={selectedUser.active ? "danger" : "primary"} onClick={() => setConfirm("status")}>{selectedUser.active ? "Deactivate User" : "Activate User"}</Button>
          </div>
          <div className="wide col-span-full grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_180px] md:items-end">
            <Field label="New Password"><Input type="password" value={password} onChange={event => setPassword(event.target.value)} placeholder="New password" /></Field>
            <Button type="button" className="min-h-[52px] w-full" disabled={!password} onClick={() => action(() => usersApi.resetPassword(selectedUser.id, password), "Password reset")}>Reset Password</Button>
          </div>
        </form>
      )}
      {confirm === "delete" && <ConfirmModal title="Delete user permanently?" message={`Delete ${selectedUser.name}. This is only allowed after their projects and tasks are reassigned.`} confirmLabel="Delete User" onClose={() => setConfirm(null)} onConfirm={removeUser} />}
      {confirm === "status" && <ConfirmModal title={selectedUser.active ? "Deactivate user?" : "Activate user?"} message={`This will ${selectedUser.active ? "block" : "restore"} login access for ${selectedUser.name}.`} confirmLabel={selectedUser.active ? "Deactivate" : "Activate"} onClose={() => setConfirm(null)} onConfirm={toggleActive} />}
    </Modal>
  );
}
