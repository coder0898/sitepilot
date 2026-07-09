import { api } from "./client";

export const tasksApi = {
  update: (taskId, payload) => api(`/api/tasks/${taskId}`, { method: "PUT", body: JSON.stringify(payload) }),
  supervisorUpdate: (taskId, formData) => api(`/api/tasks/${taskId}/supervisor-update`, { method: "POST", body: formData }),
  review: (taskId, payload) => api(`/api/tasks/${taskId}/review`, { method: "POST", body: JSON.stringify(payload) }),
  supervisorToday: () => api("/api/supervisor/today"),
};
