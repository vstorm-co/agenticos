import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { KBDetailSkeleton } from "./kb-detail-skeleton";

it("reserves the actual document columns and shared loading rows", () => {
  const { container } = render(<KBDetailSkeleton showGaps />);
  expect(container.firstChild).toHaveAttribute("aria-busy", "true");
  expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Type / size" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Upload/ })).not.toBeInTheDocument();
});

it("does not promise document rows when opening another collection tab", () => {
  render(<KBDetailSkeleton tab="sync" />);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
