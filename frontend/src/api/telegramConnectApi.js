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
  generateVendorContactCode: (vendorContactId) => api("/api/v2/telegram/connect-code", {
    method: "POST",
    body: JSON.stringify({ vendor_contact_id: vendorContactId }),
  }),
  unlinkVendorContact: (vendorContactId) => api("/api/v2/telegram/unlink", {
    method: "POST",
    body: JSON.stringify({ vendor_contact_id: vendorContactId }),
  }),
};
