import { api } from "./client";

function query(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  return search.toString() ? `?${search}` : "";
}

export const templatesApi = {
  list: (params, options = {}) => api(`/api/v2/templates${query(params)}`, options),
  getVersion: (versionId, options = {}) => api(`/api/v2/templates/versions/${versionId}`, options),
  listTasks: (versionId, params, options = {}) => api(`/api/v2/templates/versions/${versionId}/tasks${query(params)}`, options),
  listDependencies: (versionId, params, options = {}) => api(`/api/v2/templates/versions/${versionId}/dependencies${query(params)}`, options),
  listGates: (versionId, params, options = {}) => api(`/api/v2/templates/versions/${versionId}/gates${query(params)}`, options),
};