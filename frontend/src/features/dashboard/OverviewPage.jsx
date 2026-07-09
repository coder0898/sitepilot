import { Card, Pill } from "../../components/ui";

function ProjectTable({ projects }) {
  return <div className="table-wrap"><table><thead><tr><th>Project</th><th>Client</th><th>PM</th><th>Supervisor</th><th>Progress</th><th>Status</th></tr></thead><tbody>{projects.map(p => <tr key={p.id}><td>{p.name}</td><td>{p.client_name}</td><td>{p.project_manager_name}</td><td>{p.supervisor_name}</td><td>{p.progress}%</td><td><Pill tone="green">{p.status}</Pill></td></tr>)}</tbody></table></div>;
}

export function OverviewPage({ data }) {
  const approved = data.projects.reduce((sum, p) => sum + p.approved_tasks, 0);
  const total = data.projects.reduce((sum, p) => sum + p.total_tasks, 0);
  const stat = (label, value, sub) => <article><span>{label}</span><strong>{value}</strong><small>{sub}</small></article>;
  return <div className="stack">
    <div className="stats-grid">
      {stat("Projects", data.projects.length, "active calendars")}
      {stat("Users", data.users?.length || 0, "team logins")}
      {stat("Vendors", data.vendors.length, "contacts")}
      {stat("Approved", total ? `${Math.round(approved / total * 100)}%` : "0%", "task completion")}
    </div>
    <Card><div className="panel-title"><div><p>Recent projects</p><h2>Execution health</h2></div></div><ProjectTable projects={data.projects} /></Card>
  </div>;
}
