import { api } from "./client";
export const executionApi = {
  get: options => api("/api/v2/execution", options),
  createProject: payload => api("/api/v2/execution/projects", { method:"POST", body:JSON.stringify(payload) }),
  updateProject: (id,payload) => api(`/api/v2/execution/projects/${id}`, { method:"PUT", body:JSON.stringify(payload) }),
  deleteProject: id => api(`/api/v2/execution/projects/${id}`, { method:"DELETE" }),
  createTask: payload => api("/api/v2/execution/tasks", { method:"POST", body:JSON.stringify(payload) }),
  updateTask: (id,payload) => api(`/api/v2/execution/tasks/${id}`, { method:"PUT", body:JSON.stringify(payload) }),
  deleteTask: id => api(`/api/v2/execution/tasks/${id}`, { method:"DELETE" }),
  updateStatus: (id,status) => api(`/api/v2/execution/tasks/${id}/status`, { method:"PATCH", body:JSON.stringify({ status }) }),
  submitTask: (id,formData) => api(`/api/v2/execution/tasks/${id}/submit`, { method:"POST", body:formData }),
  reviewTask: (id,action,rejectionReason) => api(`/api/v2/execution/tasks/${id}/review`, { method:"POST", body:JSON.stringify({ action, rejection_reason: rejectionReason || null }) }),
  reportDelay: (id,payload) => api(`/api/v2/execution/tasks/${id}/delay-report`, { method:"POST", body:JSON.stringify(payload) }),
  rescheduleTask: (id,payload) => api(`/api/v2/execution/tasks/${id}/reschedule`, { method:"POST", body:JSON.stringify(payload) }),
  retryNotification: id => api(`/api/v2/execution/notifications/${id}/retry`, { method:"POST" }),
  createTemplate: payload => api("/api/v2/execution/templates", { method:"POST", body:JSON.stringify(payload) }),
};
