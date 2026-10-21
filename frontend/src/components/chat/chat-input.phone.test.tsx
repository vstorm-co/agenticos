import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInput } from "./chat-input";

/**
 * The composer inside the phone app (#2097): "+" opens the app's own attach
 * sheet, and opening the chat offers a photo taken a moment ago. Both answer
 * with files the app read, which go up as a picked file would.
 */

const env = vi.hoisted(() => ({
  shell: { platform: "android", version: "0.1.0", window: "main", vibrancy: false } as unknown,
  sheet: vi.fn(async (): Promise<unknown> => null),
  offer: vi.fn(async (): Promise<unknown> => null),
  upload: vi.fn(async (file: File) => ({
    id: `f-${file.name}`,
    filename: file.name,
    mime_type: "image/png",
    size: 3,
    file_type: "image",
    preview: null,
  })),
  report: vi.fn(),
  warning: vi.fn(),
}));
vi.mock("@/hooks/use-shell", () => ({ useShell: () => env.shell }));
vi.mock("@/lib/mobile/attach", () => ({ openAttachSheet: env.sheet, offerRecentPhoto: env.offer }));
vi.mock("@/lib/file-api", async (original) => ({
  ...(await original<typeof import("@/lib/file-api")>()),
  uploadFile: env.upload,
}));
vi.mock("@/lib/desktop/shell", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/shell")>()),
  reportShellFailure: env.report,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn(), warning: env.warning } }));
vi.mock("@/hooks/use-mentionables", () => ({
  useMentionables: () => ({ items: [], isLoading: false, isError: false }),
}));

const photo = (name: string) => new File(["png"], name, { type: "image/png" });

async function openSheet() {
  await userEvent.click(screen.getAllByRole("button", { name: "Add to message" })[0]!);
  await userEvent.click(await screen.findByRole("menuitem", { name: /Attach/ }));
}

beforeEach(() => {
  vi.clearAllMocks();
  env.shell = { platform: "android", version: "0.1.0", window: "main", vibrancy: false };
  env.sheet.mockImplementation(async () => null);
  env.offer.mockImplementation(async () => null);
});

describe("ChatInput in the phone app", () => {
  it("uploads what the attach sheet hands back, and names what it could not read", async () => {
    env.sheet.mockImplementation(async () => ({
      text: "",
      files: [photo("a.png"), photo("b.png")],
      refused: ["huge.mov"],
    }));
    render(<ChatInput onSend={vi.fn()} />);
    await openSheet();
    await waitFor(() => expect(env.upload).toHaveBeenCalledTimes(2));
    expect(env.warning).toHaveBeenCalledWith("Could not attach: huge.mov");
  });

  it("uploads nothing when the sheet is put away, and reports a sheet that failed", async () => {
    render(<ChatInput onSend={vi.fn()} />);
    await openSheet();
    env.sheet.mockRejectedValueOnce(new Error("no activity"));
    await openSheet();
    await waitFor(() =>
      expect(env.report).toHaveBeenCalledWith("could not open the attach sheet", expect.any(Error)),
    );
    expect(env.upload).not.toHaveBeenCalled();
  });

  it("offers a photo just taken on arrival and on coming back, and adds the one accepted", async () => {
    env.offer.mockImplementationOnce(async () => ({
      text: "",
      files: [photo("now.png")],
      refused: [],
    }));
    const { unmount } = render(<ChatInput onSend={vi.fn()} />);
    await waitFor(() =>
      expect(env.upload).toHaveBeenCalledWith(expect.objectContaining({ name: "now.png" })),
    );
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(env.offer).toHaveBeenCalledTimes(1);
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    env.offer.mockRejectedValueOnce(new Error("gone"));
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() =>
      expect(env.report).toHaveBeenCalledWith("could not offer a recent photo", expect.any(Error)),
    );
    unmount();
    document.dispatchEvent(new Event("visibilitychange"));
    expect(env.offer).toHaveBeenCalledTimes(2);
  });

  it("drops an offer answered after the composer is gone", async () => {
    let answer: (value: unknown) => void = () => {};
    env.offer.mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)));
    const { unmount } = render(<ChatInput onSend={vi.fn()} />);
    unmount();
    answer({ text: "", files: [photo("late.png")], refused: [] });
    await Promise.resolve();
    expect(env.upload).not.toHaveBeenCalled();
  });

  it("keeps the browser's own file picker outside the phone app", async () => {
    env.shell = null;
    render(<ChatInput onSend={vi.fn()} />);
    await openSheet();
    expect(env.sheet).not.toHaveBeenCalled();
    expect(env.offer).not.toHaveBeenCalled();
  });
});
