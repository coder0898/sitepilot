import { api } from "./client";

export const telegramConnectApi = {
  generateCode: (employeeId) => api("/api/v2/telegram/connect-code", {
    method: "POST",
    body: JSON.stringify({ employee_id: employeeId }),
  }),
  unlink: (employeeId) => api("/api/v2/telegram/unlink", {
    method: "POST",
    body: JSON.stringify({ employee_id: employeeId }),
  }),
  // Self-service (My Profile): no id is sent - the backend links the
  // logged-in person's own profile only.
  myStatus: () => api("/api/v2/telegram/me"),
  generateMyCode: () => api("/api/v2/telegram/me/connect-code", { method: "POST" }),
  unlinkMe: () => api("/api/v2/telegram/me/unlink", { method: "POST" }),
  generateVendorContactCode: (vendorContactId) => api("/api/v2/telegram/connect-code", {
    method: "POST",
    body: JSON.stringify({ vendor_contact_id: vendorContactId }),
  }),
  unlinkVendorContact: (vendorContactId) => api("/api/v2/telegram/unlink", {
    method: "POST",
    body: JSON.stringify({ vendor_contact_id: vendorContactId }),
  }),
};
