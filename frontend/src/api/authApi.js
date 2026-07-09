import { api } from "./client";

export const authApi = {
  login: (email, password) => api("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  changePassword: (payload) => api("/api/auth/change-password", { method: "POST", body: JSON.stringify(payload) }),
  requestReset: (payload) => api("/api/auth/request-reset", { method: "POST", body: JSON.stringify(payload) }),
};
