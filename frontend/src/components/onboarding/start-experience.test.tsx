import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartExperience, StartJourney, StartVariantPicker } from "./start-experience";
import { startVariant } from "@/lib/onboarding/variants";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/components/ui/avatar-face", () => ({ AvatarFace: () => null }));
beforeEach(() => window.history.replaceState(null, "", "/onboarding"));
it.each(["conversation", "studio", "launchpad"])("validates the %s design", (value) =>
  expect(startVariant(value)).toBe(value),
);
it.each([null, "", "anything", "Studio"])("rejects unsupported design %s", (value) =>
  expect(startVariant(value)).toBeNull(),
);
it("makes Studio the default route and hides preview controls", () => {
  const { container } = render(
    <StartExperience>
      <StartVariantPicker />
    </StartExperience>,
  );
  expect(container.querySelector('[data-onboarding-variant="studio"]')).toBeInTheDocument();
  expect(screen.queryByRole("group")).not.toBeInTheDocument();
});
it("changes design without removing the workspace, stage or form instance", async () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?variant=launchpad&start-step=admin.context&workspace=org",
  );
  const { rerender } = render(
    <StartExperience>
      <StartVariantPicker />
      <input aria-label="Draft" defaultValue="Unsaved context" />
    </StartExperience>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Conversation" }));
  expect(new URLSearchParams(window.location.search).get("variant")).toBe("conversation");
  expect(window.location.search).toContain("start-step=admin.context");
  expect(window.location.search).toContain("workspace=org");
  rerender(
    <StartExperience>
      <StartVariantPicker />
      <input aria-label="Draft" defaultValue="" />
    </StartExperience>,
  );
  expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("Unsaved context");
  expect(screen.getByRole("button", { name: "Conversation" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});
it("lets people revisit observed steps without claiming they were saved", async () => {
  window.history.replaceState(null, "", "/onboarding?variant=launchpad");
  const select = vi.fn();
  render(
    <StartJourney
      steps={["one", "two", "three"]}
      current="two"
      visited={["one", "two"]}
      onSelect={select}
      label={(id) => id}
    />,
  );
  const nav = screen.getByRole("navigation");
  expect(within(nav).getByRole("button", { name: /two/ })).toHaveAttribute("aria-current", "step");
  expect(within(nav).getByRole("button", { name: /three/ })).toBeDisabled();
  await userEvent.click(within(nav).getByRole("button", { name: /one/ }));
  expect(select).toHaveBeenCalledExactlyOnceWith("one");
  expect(screen.queryByText(/complete|saved/i)).not.toBeInTheDocument();
});

it("keeps Studio's journey free of repeated agent introductions", () => {
  render(
    <StartExperience>
      <StartJourney
        steps={["workspace", "profile", "models", "tools", "team", "task"]}
        current="workspace"
        visited={["workspace"]}
        onSelect={vi.fn()}
        label={(step) => step}
      />
    </StartExperience>,
  );
  expect(screen.queryByText("Your workspace, coming together")).not.toBeInTheDocument();
  expect(screen.queryByText("Architect")).not.toBeInTheDocument();
  expect(screen.getByRole("navigation")).toBeInTheDocument();
  expect(screen.getAllByRole("button")).toHaveLength(6);
});
