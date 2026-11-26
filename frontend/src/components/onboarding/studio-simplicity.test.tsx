import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { StartExperience } from "./start-experience";
import { StartGuide } from "./start-guide";
import { StartStageArtwork } from "./start-stage-artwork";
import { StartWorkspacePreview } from "./start-workspace-preview";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/components/ui/avatar-face", () => ({
  AvatarFace: () => <span data-testid="rendered-avatar" />,
}));
vi.mock("./start-typed-message", () => ({
  StartTypedMessage: ({ message }: { message: string }) => <span>{message}</span>,
}));
vi.mock("./start-companions", () => ({
  StartCompanions: () => <span data-testid="rendered-companions" />,
}));
beforeEach(() => window.history.replaceState(null, "", "/onboarding"));
it("uses one complete helper without an extra avatar or guide label in Studio", () => {
  render(
    <StartExperience>
      <StartGuide message="Choose your workspace." />
    </StartExperience>,
  );
  expect(screen.getByText("Choose your workspace.")).toBeVisible();
  expect(screen.queryByTestId("rendered-avatar")).not.toBeInTheDocument();
  expect(screen.queryByText("Your setup companion")).not.toBeInTheDocument();
});
it("does not mount decorative artwork or workspace previews in Studio", () => {
  const { container } = render(
    <StartExperience>
      <StartStageArtwork stage="profile" />
      <StartWorkspacePreview name="Workspace" />
    </StartExperience>,
  );
  expect(container.querySelector("aside")).not.toBeInTheDocument();
  expect(screen.queryByTestId("rendered-avatar")).not.toBeInTheDocument();
  expect(screen.queryByTestId("rendered-companions")).not.toBeInTheDocument();
});
it("keeps the explicit launchpad preview's illustration available", () => {
  window.history.replaceState(null, "", "/onboarding?variant=launchpad");
  render(
    <StartExperience>
      <StartStageArtwork stage="profile" />
    </StartExperience>,
  );
  expect(screen.getAllByTestId("rendered-avatar")).toHaveLength(2);
});
