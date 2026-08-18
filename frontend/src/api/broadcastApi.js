import { api } from "./client";

function query(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  return search.toString() ? `?${search}` : "";
}

export const broadcastApi = {
  summary: () => api("/api/v2/broadcasts/summary"),
  list: (params = {}) => api(`/api/v2/broadcasts${query(params)}`),
  detail: broadcastId => api(`/api/v2/broadcasts/${broadcastId}`),
  create: payload => api("/api/v2/broadcasts", { method: "POST", body: JSON.stringify(payload) }),
  send: broadcastId => api(`/api/v2/broadcasts/${broadcastId}/send`, { method: "POST" }),
  recipients: (projectId, groups = []) => api(`/api/v2/broadcasts/recipients${query({ project_id: projectId, groups: groups.join(",") })}`),
  templates: () => api("/api/v2/broadcasts/templates"),
  createTemplate: payload => api("/api/v2/broadcasts/templates", { method: "POST", body: JSON.stringify(payload) }),
  deleteTemplate: templateId => api(`/api/v2/broadcasts/templates/${templateId}`, { method: "DELETE" }),
};
