import { api } from "./client";

export const adminVisibilityApi = {
  projectsOverview: () => api("/api/v2/admin/projects-overview"),
  activity: (params = {}) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
    });
    const query = search.toString() ? `?${search}` : "";
    return api(`/api/v2/admin/activity${query}`);
  },
};
