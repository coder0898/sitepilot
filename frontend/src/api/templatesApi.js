import { api } from "./client";

function query(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  return search.toString() ? `?${search}` : "";
}

export const templatesApi = {
  create: (payload, options = {}) => api("/api/v2/templates", { ...options, method: "POST", body: JSON.stringify(payload) }),
  cloneVersion: (versionId, payload, options = {}) => api("/api/v2/templates/versions/" + versionId + "/clone", { ...options, method: "POST", body: JSON.stringify(payload) }),
  list: (params, options = {}) => api(`/api/v2/templates${query(params)}`, options),
  getVersion: (versionId, options = {}) => api(`/api/v2/templates/versions/${versionId}`, options),
  listTasks: (versionId, params, options = {}) => api(`/api/v2/templates/versions/${versionId}/tasks${query(params)}`, options),
  createTask: (versionId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/tasks`, { ...options, method: "POST", body: JSON.stringify(payload) }),
  updateTask: (versionId, taskId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/tasks/${taskId}`, { ...options, method: "PATCH", body: JSON.stringify(payload) }),
  deleteTask: (versionId, taskId, revisionToken, options = {}) => api(`/api/v2/templates/versions/${versionId}/tasks/${taskId}${query({ revision_token: revisionToken })}`, { ...options, method: "DELETE" }),
  reorderTasks: (versionId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/tasks/reorder`, { ...options, method: "POST", body: JSON.stringify(payload) }),
  listDependencies: (versionId, params, options = {}) => api(`/api/v2/templates/versions/${versionId}/dependencies${query(params)}`, options),
  createDependency: (versionId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/dependencies`, { ...options, method: "POST", body: JSON.stringify(payload) }),
  updateDependency: (versionId, dependencyId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/dependencies/${dependencyId}`, { ...options, method: "PATCH", body: JSON.stringify(payload) }),
  deleteDependency: (versionId, dependencyId, revisionToken, options = {}) => api(`/api/v2/templates/versions/${versionId}/dependencies/${dependencyId}${query({ revision_token: revisionToken })}`, { ...options, method: "DELETE" }),
  listGates: (versionId, params, options = {}) => api(`/api/v2/templates/versions/${versionId}/gates${query(params)}`, options),
  createGate: (versionId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/gates`, { ...options, method: "POST", body: JSON.stringify(payload) }),
  updateGate: (versionId, gateId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/gates/${gateId}`, { ...options, method: "PATCH", body: JSON.stringify(payload) }),
  configureGateMappings: (versionId, gateId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/gates/${gateId}/mappings`, { ...options, method: "PUT", body: JSON.stringify(payload) }),
  deleteGate: (versionId, gateId, revisionToken, options = {}) => api(`/api/v2/templates/versions/${versionId}/gates/${gateId}${query({ revision_token: revisionToken })}`, { ...options, method: "DELETE" }),
  validateVersion: (versionId, options = {}) => api(`/api/v2/templates/versions/${versionId}/validate`, { ...options, method: "POST" }),
  publishVersion: (versionId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/publish`, { ...options, method: "POST", body: JSON.stringify(payload) }),
  archiveVersion: (versionId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}/archive`, { ...options, method: "POST", body: JSON.stringify(payload) }),
  deleteDraftVersion: (versionId, payload, options = {}) => api(`/api/v2/templates/versions/${versionId}`, { ...options, method: "DELETE", body: JSON.stringify(payload) }),
};
