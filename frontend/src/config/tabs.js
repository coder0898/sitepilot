import { BriefcaseBusiness, CalendarCheck, FolderKanban, UsersRound } from "lucide-react";

export const TAB_REGISTRY = {
  projects: { label: "Projects", help: "Project setup, ownership and lifecycle", icon: FolderKanban },
  execution: { label: "Execution", help: "Project execution workspace", icon: CalendarCheck },
  communication: { label: "Communication Hub", help: "Project contacts & quick actions", icon: BriefcaseBusiness },
  users: { label: "Users & Access", help: "People, access and your account", icon: UsersRound },
};

export const labels = Object.fromEntries(Object.entries(TAB_REGISTRY).map(([key, item]) => [key, item.label]));

export function getTabDefinition(key) {
  return TAB_REGISTRY[key];
}

export function visibleTabs(modulePermissions, role) {
  return modulePermissions.filter(key => TAB_REGISTRY[key]).map(key => {
    const label = key === "users" && !["super_admin", "admin"].includes(role) ? "My Profile" : TAB_REGISTRY[key].label;
    return [key, label];
  });
}
