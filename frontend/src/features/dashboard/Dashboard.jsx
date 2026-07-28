import { useEffect, useState } from "react";
import { dashboardApi } from "../../api/dashboardApi";
import { AppLayout } from "../../components/layout/AppLayout";
import { visibleTabs } from "../../config/tabs";
import { DashboardTab } from "./DashboardTab";

export function Dashboard({ initialUser, onLogout }) {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("projects");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

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
      setTab(tabs[0]?.[0] || "execution");
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
      onTabChange={setTab}
      onLogout={onLogout}
      onRefresh={refresh}
      notice={notice}
      onClearNotice={() => setNotice("")}
    >
      <DashboardTab tab={tab} loading={loading} data={data} user={user} action={action} />
    </AppLayout>
  );
}
