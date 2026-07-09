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
import { VendorsPage } from "../vendors/VendorsPage";

function tabsForRole(role) {
  if (role === "supervisor") return [["today", "Today"], ["projects", "Projects"], ["security", "Security"]];
  if (role === "project_manager") return [["overview", "Overview"], ["projects", "Projects"], ["vendors", "Vendors"], ["approvals", "Approvals"], ["security", "Security"]];
  return [["overview", "Overview"], ["users", "Users"], ["projects", "Projects"], ["vendors", "Vendors"], ["approvals", "Approvals"], ["security", "Security"]];
}

export function Dashboard({ initialUser, onLogout }) {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState(initialUser.role === "supervisor" ? "today" : "overview");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      setData(await dashboardApi.get());
    } catch (err) {
      const message = String(err.message || "").toLowerCase();
      if (message.includes("login") || message.includes("session") || message.includes("inactive")) {
        clearSession();
        onLogout();
        return;
      }
      setNotice(err.message);
      setData({ user: initialUser, users: [], vendors: [], projects: [], review_tasks: [] });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); }, []);

  const user = data?.user || initialUser;
  const tabs = tabsForRole(user.role);

  async function action(fn, message = "Saved") {
    try {
      await fn();
      setNotice(message);
      await refresh();
    } catch (err) {
      setNotice(err.message);
    }
  }

  return <AppLayout user={user} tabs={tabs} activeTab={tab} onTabChange={setTab} onLogout={onLogout} notice={notice} onClearNotice={() => setNotice("")}>
    {loading && <section className="panel">Loading workspace…</section>}
    {!loading && data && tab === "overview" && <OverviewPage data={data} />}
    {!loading && data && tab === "users" && <UsersPage data={data} action={action} />}
    {!loading && data && tab === "projects" && <ProjectsPage data={data} user={user} action={action} />}
    {!loading && data && tab === "vendors" && <VendorsPage data={data} action={action} />}
    {!loading && data && tab === "approvals" && <ApprovalsPage data={data} action={action} />}
    {!loading && tab === "today" && <SupervisorTodayPage action={action} />}
    {!loading && tab === "security" && <SecurityPage action={action} />}
  </AppLayout>;
}
