import { describe, expect, it } from "vitest";
import * as ExecutionPageModule from "./ExecutionPage";

// Phase 9 retired the legacy Execution workspace (calendar, task modals,
// template management) in favour of a read-only Active Project Task View
// for activated V2 projects. sanitizeLegacyExecutionWorkspace() existed
// only to guard a template-data-leakage risk inside that legacy
// workspace's payload. The new ExecutionPage never renders template data
// or any legacy workspace payload at all, so that guard has no surface
// left to protect and was intentionally removed together with the legacy
// workspace it belonged to. This file now confirms the retirement was
// deliberate instead of continuing to test removed code.
describe("legacy execution workspace retirement", () => {
  it("no longer exposes the legacy template-leakage guard", () => {
    expect(ExecutionPageModule.sanitizeLegacyExecutionWorkspace).toBeUndefined();
  });

  it("still exports the read-only ExecutionPage component", () => {
    expect(typeof ExecutionPageModule.ExecutionPage).toBe("function");
  });
});
