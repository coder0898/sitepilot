import { BriefcaseBusiness, CalendarCheck, ShieldCheck, UsersRound } from "lucide-react";

export const TAB_REGISTRY = {
  execution: { label: "Execution", help: "Three-day project scheduler", icon: CalendarCheck },
  communication: { label: "Communication Hub", help: "Project contacts & quick actions", icon: BriefcaseBusiness },
  users: { label: "Users", help: "Create and manage logins", icon: UsersRound },
  permissions: { label: "Role Permissions", help: "Control role access", icon: ShieldCheck },
};

export const labels = Object.fromEntries(Object.entries(TAB_REGISTRY).map(([key, item]) => [key, item.label]));

export function getTabDefinition(key) {
  return TAB_REGISTRY[key];
}

export const visibleTabs = modulePermissions => modulePermissions.filter(key => TAB_REGISTRY[key]).map(key => [key, TAB_REGISTRY[key].label]);
