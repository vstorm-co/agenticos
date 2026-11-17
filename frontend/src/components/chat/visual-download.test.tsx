import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VisualDownload } from "./visual-download";

const { downloadSvgPng, downloadVisual, error } = vi.hoisted(() => ({
  downloadSvgPng: vi.fn(),
  downloadVisual: vi.fn(),
  error: vi.fn(),
}));
vi.mock("./visual-actions", () => ({ downloadSvgPng, downloadVisual }));
vi.mock("sonner", () => ({ toast: { error } }));

const SVG = '<svg viewBox="0 0 100 50"><rect/></svg>';
beforeEach(() => {
  vi.clearAllMocks();
  downloadSvgPng.mockResolvedValue(undefined);
});

describe("VisualDownload", () => {
  it("offers a vector source and a PNG for a completed SVG", async () => {
    const user = userEvent.setup();
    render(<VisualDownload title="Flow" kind="svg" content={SVG} />);
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(screen.getByRole("menuitem", { name: "PNG — image for slides" })).toBeVisible();
    await user.click(screen.getByRole("menuitem", { name: "SVG — vector file" }));
    expect(downloadVisual).toHaveBeenCalledWith(
      "Flow",
      "svg",
      SVG,
      "http://localhost:8000/api/v1/artifact-content/",
    );
    expect(downloadSvgPng).not.toHaveBeenCalled();
  });

  it("prevents another download while PNG preparation is pending", async () => {
    const pending = Promise.withResolvers<void>();
    downloadSvgPng.mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<VisualDownload title="Flow" kind="svg" content={SVG} />);
    await user.click(screen.getByRole("button", { name: "Download" }));
    await user.click(screen.getByRole("menuitem", { name: "PNG — image for slides" }));
    const trigger = screen.getByRole("button", { name: "Preparing PNG…" });
    expect(trigger).toBeDisabled();
    expect(trigger).toHaveAttribute("aria-busy", "true");
    await user.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(downloadSvgPng).toHaveBeenCalledExactlyOnceWith("Flow", SVG);
    await act(async () => pending.resolve());
    expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
  });

  it("reports a failed PNG and allows the person to try again", async () => {
    downloadSvgPng.mockRejectedValueOnce(new Error("No image"));
    const user = userEvent.setup();
    render(<VisualDownload title="Flow" kind="svg" content={SVG} />);
    await user.click(screen.getByRole("button", { name: "Download" }));
    await user.click(screen.getByRole("menuitem", { name: "PNG — image for slides" }));
    await waitFor(() =>
      expect(error).toHaveBeenCalledWith("The PNG could not be downloaded. Try again."),
    );
    await user.click(screen.getByRole("button", { name: "Download" }));
    await user.click(screen.getByRole("menuitem", { name: "PNG — image for slides" }));
    await waitFor(() => expect(downloadSvgPng).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
  });

  it("opens and closes from the keyboard and restores focus", async () => {
    const user = userEvent.setup();
    render(<VisualDownload title="Flow" kind="svg" content={SVG} />);
    await user.tab();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("menu")).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toHaveFocus();
  });

  it.each(["html", "mermaid"] as const)("keeps the source download for %s", async (kind) => {
    const user = userEvent.setup();
    render(<VisualDownload title="Flow" kind={kind} content="source" />);
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(downloadVisual).toHaveBeenCalledWith(
      "Flow",
      kind,
      "source",
      "http://localhost:8000/api/v1/artifact-content/",
    );
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
