import { api } from "./client";
export const communicationApi = {
  get: () => api("/api/communication-hub"),
  updateContractor: (contractorId, payload) => api(`/api/communication-hub/contractors/${contractorId}`, { method: "PUT", body: JSON.stringify(payload) }),
  addContact: (payload) => api("/api/communication-hub/contacts", { method: "POST", body: JSON.stringify(payload) }),
  addCategory: (payload) => api("/api/communication-hub/categories", { method: "POST", body: JSON.stringify(payload) }),
  updateCategory: (categoryId, payload) => api(`/api/communication-hub/categories/${categoryId}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteCategory: (categoryId) => api(`/api/communication-hub/categories/${categoryId}`, { method: "DELETE" }),
  linkVendor: (payload) => api("/api/communication-hub/project-vendors", { method: "POST", body: JSON.stringify(payload) }),
  linkSubcontractor: (payload) => api("/api/communication-hub/relationships", { method: "POST", body: JSON.stringify(payload) }),
  unlinkSubcontractor: (relationshipId) => api(`/api/communication-hub/relationships/${relationshipId}`, { method: "DELETE" }),
  addLog: (payload) => api("/api/communication-hub/logs", { method: "POST", body: JSON.stringify(payload) }),
};