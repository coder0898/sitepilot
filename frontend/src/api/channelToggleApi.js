import { api } from "./client";

export const channelToggleApi = {
  toggle: (employeeId, channel) => api("/api/v2/channel-toggle", {
    method: "POST",
    body: JSON.stringify({ targets: [{ employee_id: employeeId }], channel }),
  }),
  toggleVendorContact: (vendorContactId, channel) => api("/api/v2/channel-toggle", {
    method: "POST",
    body: JSON.stringify({ targets: [{ vendor_contact_id: vendorContactId }], channel }),
  }),
};
