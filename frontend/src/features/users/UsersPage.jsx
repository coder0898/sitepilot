import { useState } from "react";
import { ChevronRight, UserPlus } from "lucide-react";
import { IconButton, ManagementHeader, ManagementTable, Pill } from "../../components/ui";
import { usersApi } from "../../api/usersApi";
import { roles } from "../../utils/constants";
import { initials } from "../../utils/format";
import { CreateUserModal, UserModal } from "./components/UserModals";

function UserAvatar({ name }) {
  return <span className="grid size-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 to-blue-900 text-sm font-black text-white shadow-[0_10px_22px_rgba(37,99,235,.2)]">{initials(name)}</span>;
}

export function UsersPage({ data, user, action }) {
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);

  async function create(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const result = await action(() => usersApi.create(Object.fromEntries(new FormData(form))), "User created");
    if (result?.ok !== false) { form.reset(); setCreating(false); }
  }

  const mobileCards = data.users.map(item => <button type="button" key={item.id} onClick={() => setSelected(item)} className="flex w-full items-center gap-3 bg-white p-4 text-left transition active:bg-blue-50"><UserAvatar name={item.name}/><span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><strong className="truncate text-sm text-slate-950">{item.name}</strong><Pill tone={item.active ? "green" : "gray"}>{item.active ? "Active" : "Inactive"}</Pill></span><span className="mt-1 block truncate text-xs text-slate-500">{item.email}</span><span className="mt-1 block text-xs font-bold text-blue-700">{roles[item.role]}</span></span><ChevronRight className="shrink-0 text-slate-400" size={20}/></button>);

  return <div className="grid gap-4 sm:gap-5">
    <ManagementHeader eyebrow="Access control" title="Users" subtitle="Manage team access and permissions" actionLabel="Create user" actionIcon={<UserPlus size={18}/>} onAction={() => setCreating(true)}/>
    <ManagementTable countLabel="Total users" count={data.users.length} searchPlaceholder="Search users" tableClassName="min-w-[920px] table-fixed" mobileContent={mobileCards}>
      <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500"><tr><th className="w-[21%] px-5 py-4">User</th><th className="w-[24%] px-5 py-4">Email</th><th className="w-[14%] px-5 py-4">Role</th><th className="w-[11%] px-5 py-4">Status</th><th className="w-[13%] px-5 py-4">Created</th><th className="w-[12%] px-5 py-4">Last login</th><th className="w-[72px] px-3 py-4 text-center">Action</th></tr></thead>
      <tbody className="divide-y divide-slate-100">{data.users.map(item => <tr key={item.id} className="cursor-pointer transition hover:bg-blue-50/50" onClick={() => setSelected(item)}><td className="px-5 py-4"><span className="flex min-w-0 items-center gap-3"><UserAvatar name={item.name}/><b className="truncate">{item.name}</b></span></td><td className="truncate px-5 py-4 font-bold text-slate-700">{item.email}</td><td className="px-5 py-4"><Pill>{roles[item.role]}</Pill></td><td className="px-5 py-4"><Pill tone={item.active ? "green" : "gray"}>{item.active ? "Active" : "Inactive"}</Pill></td><td className="px-5 py-4 text-slate-600">{item.created_at ? new Date(item.created_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "-"}</td><td className="px-5 py-4 text-slate-600">{item.last_login_at ? new Date(item.last_login_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "Not yet"}</td><td className="px-3 py-4 text-center"><IconButton aria-label={`View or edit ${item.name}`} title="View user" onClick={event => { event.stopPropagation(); setSelected(item); }}><ChevronRight size={20}/></IconButton></td></tr>)}</tbody>
    </ManagementTable>
    {creating && <CreateUserModal create={create} user={user} onClose={() => setCreating(false)}/>} {selected && <UserModal selectedUser={selected} currentUser={user} onClose={() => setSelected(null)} action={action}/>}
  </div>;
}
