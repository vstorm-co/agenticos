import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AiOffNotice } from "./ai-off-notice";

const permissions = vi.hoisted(() => ({ settings: false }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => permissions.settings }),
}));

beforeEach(() => {
  permissions.settings = false;
});

describe("AiOffNotice", () => {
  it("links whoever may turn assistance on to the switch", () => {
    permissions.settings = true;
    render(<AiOffNotice orgId="org-1" />);
    expect(screen.getByRole("link", { name: "Turn it on" })).toHaveAttribute(
      "href",
      "/orgs/org-1/members",
    );
  });

  it("tells anybody else who can", () => {
    render(<AiOffNotice orgId="org-1" />);
    expect(screen.getByText(/Ask an admin to turn it on/)).toBeInTheDocument();
  });
});
