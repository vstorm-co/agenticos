import { render, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { expect, it, vi } from "vitest";

import { MarkdownContent } from "./markdown-content";

// Keep the heavy renderer unavailable, as during a slow first chunk download.
vi.mock("next/dynamic", () => ({
  default: (_loader: unknown, options: { loading: ComponentType }) => options.loading,
}));

it("keeps received text and errors readable while the markdown renderer loads", () => {
  const view = render(<MarkdownContent content="An answer already received" />);
  expect(screen.getByText("An answer already received")).toBeVisible();
  view.rerender(<MarkdownContent content="An answer already received. Could not save it." />);
  expect(screen.getByText(/Could not save it/)).toBeVisible();
});

it("treats pending content as text rather than executable markup", () => {
  const { container } = render(<MarkdownContent content={'<img src=x onerror="alert(1)">'} />);
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText(/<img src=x/)).toBeVisible();
});
