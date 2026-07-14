import { useEffect, useState } from "react";
import { RotateCcw, Save, ShieldCheck } from "lucide-react";
import { permissionsApi } from "../../api/permissionsApi";
import { Button, LoadingSpinner } from "../../components/ui";
import { PermissionMatrix } from "./components/PermissionMatrix";

export function RolePermissionsPage({ action }) {
  const [data, setData] = useState({ modules: [], permissions: [] });
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      setData(await permissionsApi.get());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function toggle(role, moduleKey) {
    setData(current => ({
      ...current,
      permissions: current.permissions.map(item => item.role === role && item.module_key === moduleKey && !item.locked ? { ...item, can_view: !item.can_view } : item),
    }));
  }

  async function save() {
    await action(() => permissionsApi.save(data.permissions.map(({ role, module_key, can_view }) => ({ role, module_key, can_view }))), "Role permissions saved");
    await load();
  }

  async function reset() {
    await action(permissionsApi.reset, "Default permissions restored");
    await load();
  }

  if (loading) return <section className="permission-panel overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm [&>header]:flex [&>header]:items-center [&>header]:justify-between [&>header]:gap-4 [&>header]:border-b [&>header]:border-slate-100 [&>header]:pb-4 max-[720px]:[&>header]:grid [&_h3]:m-0 [&_h3]:font-serif [&_h3]:text-xl [&_p]:m-0 [&_p]:text-sm [&_p]:text-slate-500 [&>header>span]:flex [&>header>span]:items-center [&>header>span]:gap-2 [&>header>span]:text-xs [&>header>span]:font-bold [&>header>span]:text-emerald-700"><LoadingSpinner label="Loading role permissions…" /></section>;

  return (
    <div className="permissions-page grid gap-5">
      <section className="permission-hero grid grid-cols-[auto_1fr_auto] items-center gap-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm max-[800px]:grid-cols-[auto_1fr] max-[620px]:grid-cols-1 [&_p]:m-0 [&_p]:text-xs [&_p]:font-black [&_p]:uppercase [&_p]:tracking-wider [&_p]:text-violet-700 [&_h2]:my-1 [&_h2]:font-serif [&_h2]:text-3xl [&_span]:text-sm [&_span]:text-slate-500">
        <div className="permission-icon grid size-12 place-items-center rounded-2xl bg-violet-100 text-violet-700"><ShieldCheck /></div>
        <div><p>Super Admin control</p><h2>Role permissions</h2><span>Configure module access for the fixed Admin, Project Manager and Supervisor roles. These are system roles, not created user accounts.</span></div>
        <div className="permission-actions flex gap-2 max-[800px]:col-span-full max-[620px]:grid [&_button]:flex [&_button]:items-center [&_button]:gap-2">
          <Button variant="secondary" onClick={reset}><RotateCcw /> Restore defaults</Button>
          <Button onClick={save}><Save /> Save changes</Button>
        </div>
      </section>
      <PermissionMatrix data={data} onToggle={toggle} />
    </div>
  );
}
