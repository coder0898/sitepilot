import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AcknowledgementPill } from "./AcknowledgementPill";

describe("AcknowledgementPill", () => {
  it("says Not acknowledged until the person acknowledges on Telegram", () => {
    render(<AcknowledgementPill acknowledgedAt={null}/>);
    expect(screen.getByText("Not acknowledged")).toBeInTheDocument();
  });

  it("says Acknowledged, with when, once acknowledged", () => {
    render(<AcknowledgementPill acknowledgedAt="2026-09-27T11:23:12Z"/>);
    expect(screen.getByText("Acknowledged")).toBeInTheDocument();
    expect(screen.getByTitle(/Acknowledged on Telegram, 27 Sept? 2026/)).toBeInTheDocument();
  });
});
