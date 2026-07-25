import { api } from "./client";

function query(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => value && search.set(key, value));
  return search.toString() ? `?${search}` : "";
}

export const projectsApi = {
  list: params => api(`/api/v2/projects${query(params)}`),
  references: () => api("/api/v2/projects/reference-data"),
  detail: projectId => api(`/api/v2/projects/${projectId}`),
  activity: projectId => api(`/api/v2/projects/${projectId}/activity`),
  create: payload => api("/api/v2/projects", { method: "POST", body: JSON.stringify(payload) }),
  update: (projectId, payload) => api(`/api/v2/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  setMembership: (projectId, payload) => api(`/api/v2/projects/${projectId}/memberships`, { method: "POST", body: JSON.stringify(payload) }),
  endMembership: (projectId, membershipId, reason) => api(`/api/v2/projects/${projectId}/memberships/${membershipId}/end`, { method: "POST", body: JSON.stringify({ reason }) }),
  setStatus: (projectId, status, reason) => api(`/api/v2/projects/${projectId}/status`, { method: "POST", body: JSON.stringify({ status, reason }) }),
  remove: (projectId, payload) => api(`/api/v2/projects/${projectId}`, { method: "DELETE", body: JSON.stringify(payload) }),
};
