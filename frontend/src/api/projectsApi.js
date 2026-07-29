import { api } from "./client";

function query(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  return search.toString() ? `?${search}` : "";
}

export const projectsApi = {
  list: params => api(`/api/v2/projects${query(params)}`),
  references: () => api("/api/v2/projects/reference-data"),
  publishedTemplates: () => api("/api/v2/projects/published-template-versions"),
  detail: projectId => api(`/api/v2/projects/${projectId}`),
  activity: projectId => api(`/api/v2/projects/${projectId}/activity`),
  create: payload => api("/api/v2/projects", { method: "POST", body: JSON.stringify(payload) }),
  generateTasks: projectId => api(`/api/v2/projects/${projectId}/generate-tasks`, { method: "POST" }),
  templateReviewTasks: (projectId, params = {}) => api(`/api/v2/projects/${projectId}/template-review/tasks${query(params)}`),
  templateReviewSummary: projectId => api(`/api/v2/projects/${projectId}/template-review/summary`),
  decideTaskApplicability: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/applicability-decisions`, { method: "POST", body: JSON.stringify(payload) }),
  taskApplicabilityHistory: (projectId, taskId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/applicability-decisions`),
  createManualTask: (projectId, payload) => api(`/api/v2/projects/${projectId}/tasks`, { method: "POST", body: JSON.stringify(payload) }),
  update: (projectId, payload) => api(`/api/v2/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  setMembership: (projectId, payload) => api(`/api/v2/projects/${projectId}/memberships`, { method: "POST", body: JSON.stringify(payload) }),
  endMembership: (projectId, membershipId, reason) => api(`/api/v2/projects/${projectId}/memberships/${membershipId}/end`, { method: "POST", body: JSON.stringify({ reason }) }),
  setStatus: (projectId, status, reason) => api(`/api/v2/projects/${projectId}/status`, { method: "POST", body: JSON.stringify({ status, reason }) }),
  remove: (projectId, payload) => api(`/api/v2/projects/${projectId}`, { method: "DELETE", body: JSON.stringify(payload) }),
};
