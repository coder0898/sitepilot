import { describe, expect, it } from "vitest";
import { sanitizeLegacyExecutionWorkspace } from "./ExecutionPage";

const payload = {
  projects: [],
  days: [],
  tasks: [],
  templates: [
    { id: "active", name: "Active legacy", active: true, tasks: [] },
    { id: "archived", name: "Archived legacy", active: false, tasks: [] },
  ],
};

describe("legacy execution template leakage guard", () => {
  it("keeps legacy template management data for Super Admin", () => {
    expect(sanitizeLegacyExecutionWorkspace(payload, "super_admin").templates).toHaveLength(2);
  });

  it.each(["admin", "project_manager"])("keeps only active project-creation templates for %s", role => {
    expect(sanitizeLegacyExecutionWorkspace(payload, role).templates.map(item => item.id)).toEqual(["active"]);
  });

  it.each(["supervisor", "internal_employee"])("removes templates from %s browser state", role => {
    expect(sanitizeLegacyExecutionWorkspace(payload, role).templates).toEqual([]);
  });
});
