export const roles = {
  super_admin: "Super Admin",
  admin: "Admin",
  project_manager: "Project Manager",
  supervisor: "Supervisor",
  internal_employee: "Internal Employee",
};

// Mirrors backend `is_org_admin`: Super Admin holds every project power Admin has.
export const ORG_ADMIN_ROLES = ["super_admin", "admin"];
export const isOrgAdmin = user => ORG_ADMIN_ROLES.includes(user?.role);

export const categories = [
  "Civil", "Electrical", "Carpentry", "Ceiling", "HVAC", "Fire", "IT", "Painting",
  "Flooring", "Glass", "Furniture", "Signage", "Housekeeping", "Quality", "Documentation", "Handover",
];

export const statuses = ["pending", "in_progress", "submitted", "completed", "rejected", "delayed", "blocked"];
