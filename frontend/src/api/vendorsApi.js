import { api } from "./client";

export const vendorsApi = {
  create: (payload) => api("/api/vendors", { method: "POST", body: JSON.stringify(payload) }),
  update: (vendorId, payload) => api(`/api/vendors/${vendorId}`, { method: "PUT", body: JSON.stringify(payload) }),
  remove: (vendorId) => api(`/api/vendors/${vendorId}`, { method: "DELETE" }),
};
