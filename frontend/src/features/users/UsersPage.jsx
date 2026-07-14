import { useState } from "react";
import { UserPlus } from "lucide-react";
import { IconButton, ManagementHeader, ManagementTable, Pill } from "../../components/ui";
import { usersApi } from "../../api/usersApi";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";
import { CreateUserModal, UserModal } from "./components/UserModals";


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
    <div className="stack grid gap-5">
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
            <td className="px-5 py-4"><span className="flex min-w-0 items-center gap-3"><span className="avatar grid size-[46px] shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-blue-900 font-black text-white shadow-[0_12px_24px_rgba(11,91,211,0.22)] pastel shrink-0">{initials(item.name)}</span><b className="truncate">{item.name}</b></span></td>
            <td className="truncate px-5 py-4 font-bold text-slate-700">{item.email}</td><td className="px-5 py-4"><Pill>{roles[item.role]}</Pill></td><td className="px-5 py-4"><Pill tone={item.active ? "green" : "gray"}>{item.active ? "Active" : "Inactive"}</Pill></td>
            <td className="px-5 py-4 text-slate-600">{item.created_at ? new Date(item.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "-"}</td><td className="px-5 py-4 text-slate-600">{item.last_login_at ? new Date(item.last_login_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "Not yet"}</td>
            <td className="px-3 py-4 text-center"><IconButton className="user-action-button !grid !size-11 !place-items-center !rounded-xl !border-2 !border-blue-700 !bg-blue-700 !p-0 !text-2xl !font-bold !text-white shadow-md hover:!bg-blue-800" aria-label={`View or edit ${item.name}`} title="View user" onClick={event => { event.stopPropagation(); setSelected(item); }}><span aria-hidden="true">→</span></IconButton></td>
          </tr>)}
        </tbody>
      </ManagementTable>

      {creating && <CreateUserModal create={create} user={user} onClose={() => setCreating(false)} />}
      {selected && <UserModal selectedUser={selected} currentUser={user} onClose={() => setSelected(null)} action={action} />}
    </div>
  );
}


