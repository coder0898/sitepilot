import { api } from "./client";

export const projectsApi = {
  create: (payload) => api("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  update: (projectId, payload) => api(`/api/projects/${projectId}`, { method: "PUT", body: JSON.stringify(payload) }),
  remove: (projectId) => api(`/api/projects/${projectId}`, { method: "DELETE" }),
  days: (projectId) => api(`/api/projects/${projectId}/days`),
  tasks: (projectId, date) => api(`/api/projects/${projectId}/tasks?date_value=${date}`),
};
