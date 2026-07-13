import { useEffect, useState } from "react";
import { Check, RotateCcw, Save, ShieldCheck } from "lucide-react";
import { permissionsApi } from "../../api/permissionsApi";

const roleLabels = { admin: "Admin", project_manager: "Project Manager", supervisor: "Supervisor" };
const moduleLabels = { execution: "Execution", communication: "Communication Hub", users: "Users", overview: "Overview", projects: "Projects", approvals: "Approvals", today: "Today", security: "Security" };

export function RolePermissionsPage({ action }) {
  const [data, setData] = useState({ modules: [], permissions: [] });
  const [loading, setLoading] = useState(true);
  async function load() { setLoading(true); try { setData(await permissionsApi.get()); } finally { setLoading(false); } }
  useEffect(() => { load(); }, []);
  function toggle(role, moduleKey) { setData(current => ({ ...current, permissions: current.permissions.map(item => item.role === role && item.module_key === moduleKey && !item.locked ? { ...item, can_view: !item.can_view } : item) })); }
  async function save() { await action(() => permissionsApi.save(data.permissions.map(({ role, module_key, can_view }) => ({ role, module_key, can_view }))), "Role permissions saved"); await load(); }
  async function reset() { await action(permissionsApi.reset, "Default permissions restored"); await load(); }
  if (loading) return <section className="permission-panel">Loading role permissions...</section>;
  return <div className="permissions-page"><section className="permission-hero"><div className="permission-icon"><ShieldCheck/></div><div><p>Super Admin control</p><h2>Role permissions</h2><span>Choose which SiteOps modules appear for each role. Communication Hub remains available as the primary workspace.</span></div><div className="permission-actions"><button className="secondary-button" onClick={reset}><RotateCcw/> Restore defaults</button><button onClick={save}><Save/> Save changes</button></div></section><section className="permission-panel"><header><div><h3>Module visibility</h3><p>Changes apply the next time users refresh their workspace.</p></div><span><Check/> Backend role restrictions remain active</span></header><div className="permission-matrix"><div className="matrix-head"><strong>Module</strong>{Object.entries(roleLabels).map(([role,label]) => <strong key={role}>{label}</strong>)}</div>{data.modules.map(moduleKey => <div className="matrix-row" key={moduleKey}><div><strong>{moduleLabels[moduleKey] || moduleKey}</strong><small>{moduleKey === "communication" ? "Primary workspace · always enabled" : "Show this module in navigation"}</small></div>{Object.keys(roleLabels).map(role => { const permission = data.permissions.find(item => item.role === role && item.module_key === moduleKey); return <label className={`permission-switch ${permission?.can_view ? "on" : ""} ${permission?.locked ? "locked" : ""}`} key={role}><input type="checkbox" checked={Boolean(permission?.can_view)} disabled={permission?.locked} onChange={() => toggle(role,moduleKey)}/><span></span><b>{permission?.can_view ? "Visible" : "Hidden"}</b></label>; })}</div>)}</div></section></div>;
}

