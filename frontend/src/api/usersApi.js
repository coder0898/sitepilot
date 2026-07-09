import { api } from "./client";

export const usersApi = {
  create: (payload) => api("/api/users", { method: "POST", body: JSON.stringify(payload) }),
  update: (userId, payload) => api(`/api/users/${userId}`, { method: "PUT", body: JSON.stringify(payload) }),
  setActive: (userId, active) => api(`/api/users/${userId}/active?active=${active}`, { method: "PATCH" }),
  resetPassword: (userId, password) => api(`/api/users/${userId}/reset-password`, { method: "POST", body: JSON.stringify({ password }) }),
};
