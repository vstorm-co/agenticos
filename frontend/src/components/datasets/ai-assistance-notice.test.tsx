import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AiAssistanceNotice } from "./ai-assistance-notice";

const state = vi.hoisted(() => ({
  ai: { orgId: "o1", enabled: false } as { orgId: string | null; enabled: boolean | null },
  maySet: true,
}));
vi.mock("@/hooks/use-organizations", () => ({
  useAiAssistance: () => state.ai,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.maySet }),
}));

beforeEach(() => {
  state.ai = { orgId: "o1", enabled: false };
  state.maySet = true;
});

/** Off, the judge is skipped; the notice says so and points at whoever can change it. */
describe("AiAssistanceNotice", () => {
  it("sends somebody who may change the switch to it", () => {
    render(<AiAssistanceNotice />);

    expect(screen.getByText(/AI assistance is off in this organization/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Enable AI assistance" })).toHaveAttribute(
      "href",
      "/orgs/o1/members#org-ai-assistance",
    );
  });

  it("tells anybody else to ask an admin, without a link they could not use", () => {
    state.maySet = false;
    render(<AiAssistanceNotice />);

    expect(screen.getByText(/Ask an admin to enable AI assistance/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it.each([
    [{ orgId: "o1", enabled: true }],
    [{ orgId: "o1", enabled: null }],
    [{ orgId: null, enabled: null }],
  ])("says nothing while it is on, or before it is known", (ai) => {
    state.ai = ai;
    const { container } = render(<AiAssistanceNotice />);

    expect(container).toBeEmptyDOMElement();
  });
});
