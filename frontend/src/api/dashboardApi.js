import { api } from "./client";

export const dashboardApi = {
  get: () => api("/api/dashboard"),
};
