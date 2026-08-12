import { api, fetchBinary } from "./client";

// Flat function-per-route client for execution_tasks_v2.py, mirroring
// projectsApi.js's pattern - kept as its own client since these endpoints
// live under a separate backend router.
export const taskExecutionApi = {
  list: projectId => api(`/api/v2/projects/${projectId}/tasks`),
  // U7: advisory readiness. Reports what could start and what is holding
  // the rest up; it never moves anything.
  readiness: projectId => api(`/api/v2/projects/${projectId}/task-readiness`),
  // U2/U3: the execution-layer gates, the ones that actually get approved.
  // projectsApi.externalGates is the planning-layer counterpart.
  executionGates: projectId => api(`/api/v2/projects/${projectId}/execution-gates`),
  recordGateStatus: (projectId, gateId, payload) => api(`/api/v2/projects/${projectId}/execution-gates/${gateId}/status`, { method: "POST", body: JSON.stringify(payload) }),
  gateStatusHistory: (projectId, gateId) => api(`/api/v2/projects/${projectId}/execution-gates/${gateId}/status-history`),
  detail: (projectId, taskId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}`),
  transitionStatus: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/status`, { method: "POST", body: JSON.stringify(payload) }),
  submitProgress: (projectId, taskId, formData) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/progress`, { method: "POST", body: formData }),
  downloadEvidence: (projectId, taskId, fileId) => fetchBinary(`/api/v2/projects/${projectId}/tasks/${taskId}/evidence/${fileId}`),
  verify: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/verify`, { method: "POST", body: JSON.stringify(payload) }),
  approve: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/approve`, { method: "POST", body: JSON.stringify(payload) }),
  logBlocker: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/blockers`, { method: "POST", body: JSON.stringify(payload) }),
  resolveBlocker: (projectId, taskId, blockerId) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/blockers/${blockerId}/resolve`, { method: "POST" }),
  logDelay: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/delays`, { method: "POST", body: JSON.stringify(payload) }),
  assignSupport: (projectId, taskId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/support-assignments`, { method: "POST", body: JSON.stringify(payload) }),
  endSupportAssignment: (projectId, taskId, assignmentId, payload) => api(`/api/v2/projects/${projectId}/tasks/${taskId}/support-assignments/${assignmentId}/end`, { method: "POST", body: JSON.stringify(payload) }),
};
