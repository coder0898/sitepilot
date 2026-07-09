import { useState } from "react";
import { MoreVertical, UserPlus } from "lucide-react";
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
      <label>Email Login<input name="email" placeholder="Enter email address" required /></label>
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

  async function toggleActive() {
    await action(() => usersApi.setActive(selectedUser.id, !selectedUser.active), "User status updated");
    setConfirm(null);
    onClose();
  }

  return <Modal title="User Details" subtitle="View and manage user access" onClose={onClose}>
    <div className="profile-hero"><div className="avatar large pastel">{initials(selectedUser.name)}</div><div><h3>{selectedUser.name}</h3><p>{selectedUser.email}</p></div><Pill tone={selectedUser.active ? "green" : "gray"}>{selectedUser.active ? "Active" : "Inactive"}</Pill></div>
    <div className="detail-grid"><article><span>Role</span><strong>{roles[selectedUser.role]}</strong></article><article><span>Status</span><strong>{selectedUser.active ? "Active" : "Inactive"}</strong></article><article><span>Created</span><strong>{selectedUser.created_at ? new Date(selectedUser.created_at).toLocaleDateString("en-GB") : "ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â"}</strong></article><article><span>Last Login</span><strong>{selectedUser.last_login_at ? new Date(selectedUser.last_login_at).toLocaleString("en-GB") : "Not yet"}</strong></article></div>
    {protectedUser ? <div className="info-strip">System owner account. Protected from changes.</div> : <form className="modal-form two-col" onSubmit={save}>
      <label>Full Name<input name="name" defaultValue={selectedUser.name} required /></label>
      <label>Email Login<input name="email" defaultValue={selectedUser.email} required /></label>
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
        searchPlaceholder="Search users?"
        tableClassName="user-table"
      >
            <colgroup>
              <col className="w-[18%]" />
              <col className="w-[24%]" />
              <col className="w-[15%]" />
              <col className="w-[12%]" />
              <col className="w-[14%]" />
              <col className="w-[12%]" />
              <col className="w-[5%]" />
            </colgroup>
            <thead>
              <tr className="data-row table-head">
                <th scope="col">User</th>
                <th scope="col">Email</th>
                <th scope="col">Role</th>
                <th scope="col">Status</th>
                <th scope="col">Created On</th>
                <th scope="col">Last Login</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.users.map((item) => (
                <tr
                  key={item.id}
                  className="data-row"
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelected(item)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") setSelected(item);
                  }}
                >
                  <td data-label="User">
                    <span className="person-cell">
                      <span className="avatar pastel">{initials(item.name)}</span>
                      <span className="min-w-0">
                        <b>{item.name}</b>
                      </span>
                    </span>
                  </td>
                  <td data-label="Email"><b>{item.email}</b></td>
                  <td data-label="Role"><Pill>{roles[item.role]}</Pill></td>
                  <td data-label="Status"><Pill tone={item.active ? "green" : "gray"}>{item.active ? "Active" : "Inactive"}</Pill></td>
                  <td data-label="Created On">{item.created_at ? new Date(item.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "Ã¢â‚¬â€"}</td>
                  <td data-label="Last Login">{item.last_login_at ? new Date(item.last_login_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "Not yet"}</td>
                  <td data-label="Actions">
                    <button
                      type="button"
                      className="kebab"
                      aria-label={`Open ${item.name}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelected(item);
                      }}
                    >
                      <MoreVertical size={20} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
      </ManagementTable>

      {creating && <CreateUserModal create={create} user={user} onClose={() => setCreating(false)} />}
      {selected && <UserModal selectedUser={selected} currentUser={user} onClose={() => setSelected(null)} action={action} />}
    </div>
  );
}