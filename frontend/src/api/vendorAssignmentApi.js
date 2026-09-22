import { api } from "./client";

// Flat function-per-route client for project_vendors_v2.py, mirroring
// projectsApi.js/taskExecutionApi.js's pattern - kept as its own client
// since these endpoints live under a separate backend router.
export const vendorAssignmentApi = {
  listVendors: () => api("/api/v2/vendors"),
  listCapabilityCategories: () => api("/api/v2/vendors/capability-categories"),
  setVendorCapabilities: (vendorId, categoryIds) => api(`/api/v2/vendors/${vendorId}/capabilities`, { method: "POST", body: JSON.stringify({ category_ids: categoryIds }) }),
  listProjectVendors: (projectId, { includeEnded = false } = {}) => api(`/api/v2/projects/${projectId}/vendors${includeEnded ? "?include_ended=true" : ""}`),
  mapVendor: (projectId, payload) => api(`/api/v2/projects/${projectId}/vendors`, { method: "POST", body: JSON.stringify(payload) }),
  removeProjectVendor: (projectId, vendorId, payload) => api(`/api/v2/projects/${projectId}/vendors/${vendorId}/remove`, { method: "POST", body: JSON.stringify(payload) }),
  listTaskVendorAssignments: (projectId, taskId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/vendor-assignments`),
  delegateTask: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/vendor-assignment`, { method: "POST", body: JSON.stringify(payload) }),
  unassignTask: (projectId, taskId, assignmentId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/vendor-assignment/${assignmentId}/unassign`, { method: "POST", body: JSON.stringify(payload) }),
  acknowledge: (projectId, taskId, assignmentId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/vendor-assignment/${assignmentId}/acknowledge`, { method: "POST", body: JSON.stringify(payload) }),
};
