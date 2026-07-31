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
  executionTasks: projectId => api(`/api/v2/projects/${projectId}/execution-tasks`),
  create: payload => api("/api/v2/projects", { method: "POST", body: JSON.stringify(payload) }),
  generateTasks: projectId => api(`/api/v2/projects/${projectId}/generate-tasks`, { method: "POST" }),
  generateGates: projectId => api(`/api/v2/projects/${projectId}/generate-gates`, { method: "POST" }),
  generateDependencies: projectId => api(`/api/v2/projects/${projectId}/generate-dependencies`, { method: "POST" }),
  dependencies: (projectId, params = {}) => api(`/api/v2/projects/${projectId}/dependencies${query(params)}`),
  createDependency: (projectId, payload) => api(`/api/v2/projects/${projectId}/dependencies`, { method: "POST", body: JSON.stringify(payload) }),
  externalGates: projectId => api(`/api/v2/projects/${projectId}/external-gates`),
  decideGateApplicability: (projectId, gateId, payload) => api(`/api/v2/projects/${projectId}/gates/${gateId}/applicability-decisions`, { method: "POST", body: JSON.stringify(payload) }),
  gateApplicabilityHistory: (projectId, gateId) => api(`/api/v2/projects/${projectId}/gates/${gateId}/applicability-decisions`),
  templateReviewTasks: (projectId, params = {}) => api(`/api/v2/projects/${projectId}/template-review/tasks${query(params)}`),
  templateReviewSummary: projectId => api(`/api/v2/projects/${projectId}/template-review/summary`),
  decideTaskApplicability: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/applicability-decisions`, { method: "POST", body: JSON.stringify(payload) }),
  taskApplicabilityHistory: (projectId, taskId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/applicability-decisions`),
  createManualTask: (projectId, payload) => api(`/api/v2/projects/${projectId}/tasks`, { method: "POST", body: JSON.stringify(payload) }),
  createManualGate: (projectId, payload) => api(`/api/v2/projects/${projectId}/gates`, { method: "POST", body: JSON.stringify(payload) }),
  update: (projectId, payload) => api(`/api/v2/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  setMembership: (projectId, payload) => api(`/api/v2/projects/${projectId}/memberships`, { method: "POST", body: JSON.stringify(payload) }),
  team: projectId => api(`/api/v2/projects/${projectId}/team`),
  updateTeam: (projectId, payload) => api(`/api/v2/projects/${projectId}/team`, { method: "PATCH", body: JSON.stringify(payload) }),
  endMembership: (projectId, membershipId, reason) => api(`/api/v2/projects/${projectId}/memberships/${membershipId}/end`, { method: "POST", body: JSON.stringify({ reason }) }),
  setStatus: (projectId, status, reason) => api(`/api/v2/projects/${projectId}/status`, { method: "POST", body: JSON.stringify({ status, reason }) }),
  remove: (projectId, payload) => api(`/api/v2/projects/${projectId}`, { method: "DELETE", body: JSON.stringify(payload) }),
};
