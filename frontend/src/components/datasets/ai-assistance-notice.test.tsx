import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AiAssistanceNotice } from "./ai-assistance-notice";

const state = vi.hoisted(() => ({
  org: { id: "o1", ai_assistance_enabled: false } as {
    id: string;
    ai_assistance_enabled: boolean;
  } | null,
  maySet: true,
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({ activeOrg: state.org }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.maySet }),
}));

beforeEach(() => {
  state.org = { id: "o1", ai_assistance_enabled: false };
  state.maySet = true;
});

/** Off, the judge is skipped; the notice says so and points at whoever can change it. */
describe("AiAssistanceNotice", () => {
  it("sends somebody who may change the switch to it", () => {
    render(<AiAssistanceNotice />);

    expect(screen.getByText(/AI assistance is off in this organization/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Enable AI assistance" })).toHaveAttribute(
      "href",
      "/orgs/o1/members",
    );
  });

  it("tells anybody else to ask an admin, without a link they could not use", () => {
    state.maySet = false;
    render(<AiAssistanceNotice />);

    expect(screen.getByText(/Ask an admin to turn it on/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it.each([[{ id: "o1", ai_assistance_enabled: true }], [null]])(
    "says nothing while it is on, or before an organization is known",
    (org) => {
      state.org = org;
      const { container } = render(<AiAssistanceNotice />);

      expect(container).toBeEmptyDOMElement();
    },
  );
});
