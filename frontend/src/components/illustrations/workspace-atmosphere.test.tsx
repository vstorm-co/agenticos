import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { WorkspaceAtmosphere } from "./workspace-atmosphere";

it("keeps repeated illustrations independent and out of accessible content", () => {
  const { container } = render(
    <>
      <WorkspaceAtmosphere />
      <WorkspaceAtmosphere />
    </>,
  );
  const ids = [...container.querySelectorAll("[id]")].map((node) => node.id);
  expect(ids.length).toBeGreaterThan(0);
  expect(new Set(ids).size).toBe(ids.length);
  for (const svg of container.querySelectorAll("svg")) {
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("focusable", "false");
  }
  expect(screen.queryByRole("img")).toBeNull();
});
