import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResourceUnavailable } from "./resource-unavailable";

const state = vi.hoisted(() => ({ organizations: [] as { id: string }[] }));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizationList: () => ({ data: state.organizations }),
}));

describe("ResourceUnavailable", () => {
  it("keeps the tenant hint and retry together with the way back", () => {
    state.organizations = [{ id: "one" }, { id: "two" }];
    const retry = vi.fn();
    const { container } = render(
      <ResourceUnavailable
        back="/agents"
        label="Back to agents"
        retry={{ label: "Try again", onClick: retry }}
      />,
    );
    expect(container.firstElementChild).toContainElement(
      screen.getByText(/switch to it in the organization menu/),
    );
    expect(container.firstElementChild).toContainElement(
      screen.getByRole("button", { name: "Try again" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it.each([1, 2])(
    "offers an organization hint only when another organization exists (%s)",
    (count) => {
      state.organizations = Array.from({ length: count }, (_, index) => ({ id: String(index) }));
      render(<ResourceUnavailable back="/agents" label="Back to agents" />);
      expect(screen.getByRole("link", { name: "Back to agents" })).toHaveAttribute(
        "href",
        "/agents",
      );
      expect(screen.queryByText(/switch to it in the organization menu/)).toBe(
        count > 1 ? screen.getByText(/switch to it in the organization menu/) : null,
      );
    },
  );
});
