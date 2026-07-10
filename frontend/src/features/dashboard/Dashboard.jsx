import { useEffect, useState } from "react";
import { clearSession } from "../../api/client";
import { dashboardApi } from "../../api/dashboardApi";
import { AppLayout } from "../../components/layout/AppLayout";
import { ApprovalsPage } from "../approvals/ApprovalsPage";
import { OverviewPage } from "../dashboard/OverviewPage";
import { ProjectsPage } from "../projects/ProjectsPage";
import { SecurityPage } from "../security/SecurityPage";
import { SupervisorTodayPage } from "../supervisor/SupervisorTodayPage";
import { UsersPage } from "../users/UsersPage";
import { CommunicationHubPage } from "../communication/CommunicationHubPage";
import { RolePermissionsPage } from "../permissions/RolePermissionsPage";

const tabLabels = { communication: "Communication Hub", users: "Users", permissions: "Role Permissions", overview: "Overview", projects: "Projects", approvals: "Approvals", today: "Today", security: "Security" };
function tabsFromPermissions(keys = ["communication"]) { return keys.filter(key => tabLabels[key]).map(key => [key, tabLabels[key]]); }

export function Dashboard({ initialUser, onLogout }) {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("communication");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  async function refresh() {
    setLoading(true);
    try { setData(await dashboardApi.get()); }
    catch (err) { const message = String(err.message || "").toLowerCase(); if (message.includes("login") || message.includes("session") || message.includes("inactive")) { clearSession(); onLogout(); return; } setNotice(err.message); setData({ user: initialUser, users: [], vendors: [], projects: [], review_tasks: [], module_permissions: ["communication"] }); }
    finally { setLoading(false); }
  }
  useEffect(() => { refresh(); }, []);
  const user = data?.user || initialUser;
  const tabs = tabsFromPermissions(data?.module_permissions || ["communication"]);
  useEffect(() => { if (data && !tabs.some(([key]) => key === tab)) setTab(tabs[0]?.[0] || "communication"); }, [data, tab]);
  async function action(fn, message = "Saved") { try { await fn(); setNotice(message); await refresh(); } catch (err) { setNotice(err.message); } }
  return <AppLayout user={user} tabs={tabs} activeTab={tab} onTabChange={setTab} onLogout={onLogout} onRefresh={refresh} notice={notice} onClearNotice={() => setNotice("")}>
    {loading && <section className="panel">Loading workspace…</section>}
    {!loading && data && tab === "communication" && <CommunicationHubPage user={user} action={action}/>}
    {!loading && data && tab === "users" && <UsersPage data={data} user={user} action={action}/>}
    {!loading && data && tab === "permissions" && user.role === "super_admin" && <RolePermissionsPage action={action}/>}
    {!loading && data && tab === "overview" && <OverviewPage data={data}/>}
    {!loading && data && tab === "projects" && <ProjectsPage data={data} user={user} action={action}/>}
    {!loading && data && tab === "approvals" && <ApprovalsPage data={data} action={action}/>}
    {!loading && tab === "today" && <SupervisorTodayPage action={action}/>}
    {!loading && tab === "security" && <SecurityPage action={action}/>}
  </AppLayout>;
}
