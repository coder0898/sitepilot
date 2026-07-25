import { LoadingSpinner } from "../../components/ui";
import { CommunicationHubPage } from "../communication/CommunicationHubPage";
import { ExecutionPage } from "../execution/ExecutionPage";
import { ProjectsPage } from "../projects/ProjectsPage";
import { UsersPage } from "../users/UsersPage";

const TAB_COMPONENTS = {
  projects: ProjectsPage,
  execution: ExecutionPage,
  communication: CommunicationHubPage,
  users: UsersPage,
};

export function DashboardTab({ tab, loading, data, user, action }) {
  if (loading) {
    return <section className="rounded-[28px] border border-slate-200/80 bg-white p-6 shadow-[0_18px_60px_rgba(15,23,42,.06)]"><LoadingSpinner label="Loading workspace…" /></section>;
  }
  const Component = TAB_COMPONENTS[tab];
  if (!Component) return null;
  return <Component data={data} user={user} action={action} />;
}
