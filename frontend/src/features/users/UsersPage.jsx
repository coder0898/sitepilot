import { useState } from "react";
import { MoreVertical, UserPlus } from "lucide-react";
import { ManagementHeader, ManagementTable, Modal, Pill } from "../../components/ui";
import { usersApi } from "../../api/usersApi";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";

function CreateUserModal({ create, onClose }) {
  return <Modal title="Create User" subtitle="Create a role-based login" onClose={onClose}>
    <form className="modal-form two-col" onSubmit={create}>
      <label>Full Name<input name="name" placeholder="Enter full name" required /></label>
      <label>Email Login<input name="email" placeholder="Enter email address" required /></label>
      <label>Temporary Password<input name="password" type="password" placeholder="Enter temporary password" required /></label>
      <label>Role<select name="role" defaultValue="" required><option value="" disabled>Select role</option><option value="admin">Admin</option><option value="project_manager">Project Manager</option><option value="supervisor">Supervisor</option></select></label>
      <button><UserPlus size={18} /> Create User</button>
    </form>
  </Modal>;
}

function UserModal({ user, onClose, action }) {
  const [pwd, setPwd] = useState("");
  return <Modal title="User Details" subtitle="Profile, status and access control" onClose={onClose}>
    <div className="profile-hero"><div className="avatar large pastel">{initials(user.name)}</div><div><h3>{user.name}</h3><p>{user.email}</p></div><Pill tone={user.active ? "green" : "gray"}>{user.active ? "Active" : "Inactive"}</Pill></div>
    <div className="detail-grid"><article><span>Role</span><strong>{roles[user.role]}</strong></article><article><span>Status</span><strong>{user.active ? "Active" : "Inactive"}</strong></article><article><span>Created</span><strong>{user.created_at ? new Date(user.created_at).toLocaleDateString("en-GB") : "—"}</strong></article><article><span>Last Login</span><strong>{user.last_login_at ? new Date(user.last_login_at).toLocaleString("en-GB") : "Not yet"}</strong></article></div>
    {user.role === "super_admin" ? <div className="info-strip">System owner account. Protected from changes.</div> : <div className="modal-actions split-actions"><button className={user.active ? "danger" : ""} onClick={() => action(() => usersApi.setActive(user.id, !user.active), "User status updated")}>{user.active ? "Deactivate User" : "Activate User"}</button><div className="inline-reset"><input type="password" value={pwd} onChange={e => setPwd(e.target.value)} placeholder="New password" /><button onClick={() => action(() => usersApi.resetPassword(user.id, pwd), "Password reset")}>Reset Password</button></div></div>}
  </Modal>;
}

export function UsersPage({ data, action }) {
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
  return <div className="stack">
    <ManagementHeader eyebrow="Access control" title="Users" subtitle="Manage team access and permissions" actionLabel="Create User" actionIcon={<UserPlus size={18} />} onAction={() => setCreating(true)} />
    <ManagementTable countLabel="Total Users" count={data.users.length} searchPlaceholder="Search users?" showGrid>
      <div className="data-table user-table">
        <div className="data-row table-head"><span>User</span><span>Role</span><span>Status</span><span>Created On</span><span>Last Login</span><span>Actions</span></div>
        {data.users.map(u => <button className="data-row" key={u.id} onClick={() => setSelected(u)}><span className="person-cell"><span className="avatar pastel">{initials(u.name)}</span><span><b>{u.name}</b><small>{u.email}</small></span></span><span><Pill>{roles[u.role]}</Pill></span><span><Pill tone={u.active ? "green" : "gray"}>{u.active ? "Active" : "Inactive"}</Pill></span><span>{u.created_at ? new Date(u.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—"}</span><span>{u.last_login_at ? new Date(u.last_login_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "Not yet"}</span><span><span className="kebab"><MoreVertical size={20} /></span></span></button>)}
      </div>
    </ManagementTable>
    {creating && <CreateUserModal create={create} onClose={() => setCreating(false)} />}
    {selected && <UserModal user={selected} onClose={() => setSelected(null)} action={action} />}
  </div>;
}
