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
};
