import { LoadingSpinner } from "../../components/ui";
import { CommunicationHubPage } from "../communication/CommunicationHubPage";
import { ExecutionPage } from "../execution/ExecutionPage";
import { RolePermissionsPage } from "../permissions/RolePermissionsPage";
import { UsersPage } from "../users/UsersPage";

const TAB_COMPONENTS = {
  execution: ExecutionPage,
  communication: CommunicationHubPage,
  users: UsersPage,
  permissions: RolePermissionsPage,
};

export function DashboardTab({ tab, loading, data, user, action }) {
  if (loading) {
    return <section className="panel rounded-2xl border border-slate-200 bg-white p-6 shadow-[0_12px_40px_rgba(15,23,42,0.06)]"><LoadingSpinner label="Loading workspace?" /></section>;
  }

  if (tab === "permissions" && user.role !== "super_admin") return null;

  const Component = TAB_COMPONENTS[tab];
  if (!Component) return null;

  return <Component data={data} user={user} action={action} />;
}
