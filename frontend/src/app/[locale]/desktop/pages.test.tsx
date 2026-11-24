import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BlobbyPage from "./blobby/page";
import QuickAskPage from "./quick-ask/page";

const env = vi.hoisted(() => ({ shell: null as unknown }));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/components/desktop/blobby-window", () => ({ BlobbyWindow: () => <p>blobby</p> }));
vi.mock("@/components/desktop/quick-ask-workspace", () => ({
  QuickAskWorkspace: () => <p>quick ask</p>,
}));

const MAC = { platform: "macos", window: "main", version: "test", vibrancy: true };

beforeEach(() => {
  env.shell = null;
});

describe.each([
  ["/desktop/blobby", BlobbyPage, "blobby"],
  ["/desktop/quick-ask", QuickAskPage, "quick ask"],
] as [string, () => ReactElement, string][])("%s", (_path, Page, content) => {
  it("is one screen saying it opens in the desktop app, in a browser", () => {
    render(<Page />);
    expect(screen.getAllByText("This opens in the AgenticOS desktop app.")).toHaveLength(1);
    expect(screen.queryByText(content)).toBeNull();
  });

  it("is the window itself inside the app", () => {
    env.shell = MAC;
    render(<Page />);
    expect(screen.getByText(content)).toBeInTheDocument();
  });
});
