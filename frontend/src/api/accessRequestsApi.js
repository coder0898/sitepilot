import { api } from "./client";

export const accessRequestsApi = {
  create: payload => api("/api/access-requests", { method: "POST", body: JSON.stringify(payload) }),
  createOnBehalf: payload => api("/api/access-requests/on-behalf", { method: "POST", body: JSON.stringify(payload) }),
  verify: () => api("/api/access-requests/verify", { method: "POST", authFailure: "preserve" }),
  list: () => api("/api/access-requests"),
  events: id => api(`/api/access-requests/${id}/events`),
  approve: (id, payload) => api(`/api/access-requests/${id}/approve`, { method: "POST", body: JSON.stringify(payload) }),
  reject: (id, payload) => api(`/api/access-requests/${id}/reject`, { method: "POST", body: JSON.stringify(payload) }),
  resendVerification: id => api(`/api/access-requests/${id}/resend-verification`, { method: "POST" }),
  resendActivation: id => api(`/api/access-requests/${id}/resend-activation`, { method: "POST" }),
};