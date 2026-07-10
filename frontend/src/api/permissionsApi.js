import { api } from "./client";
export const permissionsApi = {
  get: () => api("/api/role-permissions"),
  save: (permissions) => api("/api/role-permissions", { method: "PUT", body: JSON.stringify({ permissions }) }),
  reset: () => api("/api/role-permissions/reset", { method: "POST" }),
};