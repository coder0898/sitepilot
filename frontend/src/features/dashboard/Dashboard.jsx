import { useEffect, useState } from "react";
import { dashboardApi } from "../../api/dashboardApi";
import { AppLayout } from "../../components/layout/AppLayout";
import { visibleTabs } from "../../config/tabs";
import { useRoute } from "../../lib/route";
import { DashboardTab } from "./DashboardTab";

export function Dashboard({ initialUser, onLogout }) {
  const [data, setData] = useState(null);
  const [route, setRoute] = useRoute();
  const tab = route.tab || "projects";
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  // Switching module tabs drops any project selection the Projects tab was
  // holding, otherwise ?project= survives into Templates and reappears when
  // you come back - stale and confusing.
  function changeTab(next) {
    setRoute({ tab: next, project: "", pane: "" });
  }

  function openProject(code) {
    setRoute({ tab: "projects", project: code, pane: "overview" });
  }

  async function refresh() {
    setLoading(true);
    try {
      setData(await dashboardApi.get());
    } catch (error) {
      const message = String(error.message || "").toLowerCase();
      if (message.includes("login") || message.includes("session") || message.includes("inactive")) {
        onLogout();
        return;
      }
      setNotice(error.message);
      setData({ user: initialUser, users: [], module_permissions: ["projects", "execution", "communication"] });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const user = data?.user || initialUser;
  const tabs = visibleTabs(data?.module_permissions || ["users"], user.role);

  useEffect(() => {
    if (data && !tabs.some(([key]) => key === tab)) {
      // replace, not push: an unreachable tab in the URL should not become a
      // history entry the Back button can return the user to.
      setRoute({ tab: tabs[0]?.[0] || "execution", project: "", pane: "" }, { replace: true });
    }
  }, [data, tab]);

  async function action(operation, message = "Saved", options = {}) {
    try {
      await operation();
      setNotice(message);
      if (options.refresh !== false) await refresh();
      return { ok: true };
    } catch (error) {
      const errorMessage = error.message || "Something went wrong";
      setNotice(errorMessage);
      return { ok: false, error: errorMessage };
    }
  }

  return (
    <AppLayout
      user={user}
      tabs={tabs}
      activeTab={tab}
      onTabChange={changeTab}
      onLogout={onLogout}
      onRefresh={refresh}
      notice={notice}
      onClearNotice={() => setNotice("")}
    >
      <DashboardTab tab={tab} loading={loading} data={data} user={user} action={action} onOpenProject={openProject} />
    </AppLayout>
  );
}
