import { describe, expect, it } from "vitest";
import { visibleTabs } from "./tabs";

const modules = ["projects", "execution", "communication", "users"];
const keysFor = role => visibleTabs(modules, role).map(([key]) => key);

describe("template navigation visibility", () => {
  it.each(["super_admin", "admin", "project_manager"])("shows Templates for %s", role => {
    expect(keysFor(role)).toContain("templates");
  });

  it.each(["supervisor", "internal_employee"])("hides Templates for %s", role => {
    expect(keysFor(role)).not.toContain("templates");
  });
});