import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactFrame, ArtifactFrameView, type DataBridge } from "./artifact-frame";
import { ArtifactThumbnail } from "./artifact-thumbnail";
import { PublicArtifact } from "./public-artifact";
import { MAX_CANCELS, useArtifactActions, useAskingGate } from "@/hooks/use-artifact-actions";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { ArtifactActionRun, ArtifactActionView, ArtifactVersion } from "@/types/artifact";

/**
 * What the console does when a page asks to run a workflow (#1976).
 *
 * The page's script is untrusted: it can post a request without a click, in a
 * loop, under any name. So the frame's own window and the load's nonce are the
 * only senders listened to, the server's list of actions decides what a name
 * means, and a person agrees to every run.
 */

const useArtifactViewMock = vi.fn();
const useArtifactDataMock = vi.fn();
const IDLE_READ = {
  data: undefined,
  error: null,
  isError: false,
  isFetching: false,
  dataUpdatedAt: 0,
  errorUpdatedAt: 0,
  refetch: vi.fn(),
};
const useArtifactReasonsMock = vi.fn().mockReturnValue(IDLE_READ);
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifactView: (...args: unknown[]) => useArtifactViewMock(...args),
  useArtifactData: (...args: unknown[]) => useArtifactDataMock(...args),
  useArtifactReasons: (...args: unknown[]) => useArtifactReasonsMock(...args),
}));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

const SEND: ArtifactActionView = {
  workflow_id: "w1",
  name: "Send report",
  label: "Send it <b>now</b>",
  fields: [
    {
      name: "to",
      label: "Recipient",
      type: "text",
      required: true,
      description: null,
      options: [],
    },
    {
      name: "copies",
      label: null,
      type: "integer",
      required: false,
      description: null,
      options: [],
    },
  ],
};
const TIDY: ArtifactActionView = {
  workflow_id: "w2",
  name: "Archive deals",
  label: "Tidy",
  fields: [],
};

const RUNNING: ArtifactActionRun = {
  status: "running",
  finished: false,
  paused: false,
  run_path: null,
  output_text: null,
  output_structured: null,
  error_message: null,
};
const DONE: ArtifactActionRun = {
  ...RUNNING,
  status: "completed",
  finished: true,
  output_text: "Sent",
};

function viewOf(over: Record<string, unknown> = {}) {
  return {
    isLoading: false,
    dataUpdatedAt: 1,
    data: {
      url: "https://x/c/t",
      nonce: "n1",
      live: false,
      injected: false,
      version: { id: "v1" } as ArtifactVersion,
      actions_enabled: true,
      actions: [SEND, TIDY],
      ...over,
    },
  };
}

function wrapped(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

const FRAME = <ArtifactFrame artifactId="a1" versionId={null} title="Q3 page" />;

function page(node: React.ReactElement = FRAME, loaded = true) {
  const view = render(wrapped(node));
  const frame = screen.getByTitle("Q3 page") as HTMLIFrameElement;
  const post = vi.spyOn(frame.contentWindow!, "postMessage").mockImplementation(() => {});
  // The document has loaded, as it has by the time a person can be asked anything.
  if (loaded) fireEvent.load(frame);
  /** Every message the console posted to the page, oldest first. */
  const sent = () => post.mock.calls.map(([message]) => message as Record<string, unknown>);
  const rejected = () => sent().filter((message) => message.event === "rejected");
  return { ...view, frame, post, sent, rejected };
}

function ask(frame: HTMLIFrameElement, data: unknown, source: unknown = frame.contentWindow) {
  act(() => {
    window.dispatchEvent(
      new MessageEvent("message", { data, source: source as MessageEventSource }),
    );
  });
}

const REQUEST = { type: "agenticos:run", n: "n1", id: "r1", action: "w1", input: { to: "a@b.c" } };

const dialog = () => screen.queryByRole("dialog");
const runButton = () => screen.getByRole("button", { name: "Run" });
const cancelButton = () => screen.getByRole("button", { name: "Cancel" });

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Opens the dialog for `REQUEST` and waits out the delay on Run. */
async function open(frame: HTMLIFrameElement, over: Record<string, unknown> = {}) {
  ask(frame, { ...REQUEST, ...over });
  await advance(500);
}

describe("a page asking the console to run an action", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useArtifactViewMock.mockReturnValue(viewOf());
    useArtifactDataMock.mockReturnValue({
      data: undefined,
      error: null,
      isError: false,
      isFetching: false,
      dataUpdatedAt: 0,
      errorUpdatedAt: 0,
      refetch: vi.fn(),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  describe("who is listened to", () => {
    it("ignores a message from any other window", () => {
      const { frame, sent } = page();
      ask(frame, REQUEST, window);
      ask(frame, REQUEST, null);
      expect(dialog()).toBeNull();
      expect(sent()).toEqual([]);
    });

    it("ignores a message under another nonce, or with none", () => {
      const { frame, sent } = page();
      ask(frame, { ...REQUEST, n: "n0" });
      ask(frame, { ...REQUEST, n: undefined });
      expect(dialog()).toBeNull();
      expect(sent()).toEqual([]);
    });

    it.each([
      ["a string", "agenticos:run"],
      ["null", null],
      ["another type", { ...REQUEST, type: "agenticos:ready" }],
      ["no id", { ...REQUEST, id: undefined }],
      ["an empty id", { ...REQUEST, id: "" }],
      ["a long id", { ...REQUEST, id: "x".repeat(201) }],
      ["no action", { ...REQUEST, action: undefined }],
      ["an empty action", { ...REQUEST, action: "" }],
      ["a long action", { ...REQUEST, action: "x".repeat(201) }],
      ["no input", { ...REQUEST, input: undefined }],
      ["a null input", { ...REQUEST, input: null }],
      ["an array input", { ...REQUEST, input: [1] }],
      ["a string input", { ...REQUEST, input: "to" }],
    ])("ignores %s without a word back", (_, message) => {
      const { frame, sent } = page();
      ask(frame, message);
      expect(dialog()).toBeNull();
      expect(sent()).toEqual([]);
    });

    it("never listens when the address is not the viewer's", () => {
      useArtifactViewMock.mockReturnValue(viewOf({ actions_enabled: false }));
      const { frame, sent } = page();
      ask(frame, REQUEST);
      expect(dialog()).toBeNull();
      expect(sent()).toEqual([]);
    });

    it("is never listened for by the frame a public link, an embed or a card draws", () => {
      const view = render(<ArtifactFrameView url="https://x/c/t" title="Q3 page" />);
      const frame = view.getByTitle("Q3 page") as HTMLIFrameElement;
      const post = vi.spyOn(frame.contentWindow!, "postMessage").mockImplementation(() => {});
      ask(frame, REQUEST);
      expect(dialog()).toBeNull();
      expect(post).not.toHaveBeenCalled();
    });

    it("is never listened for on a public page", () => {
      const opened = {
        password_required: false as const,
        title: "Q3 page",
        published_at: "2026-09-22T10:00:00Z",
        view: {
          url: "https://x/c/t",
          expires_at: "",
          nonce: "n1",
          live: false,
          injected: false,
          awaiting_consent: false,
          bindings: 0,
          version: { id: "v1" } as ArtifactVersion,
          actions_enabled: true,
          actions: [SEND],
        },
      };
      render(<PublicArtifact artifact={opened} publicKey="k" />);
      const frame = screen.getByTitle("Q3 page") as HTMLIFrameElement;
      const post = vi.spyOn(frame.contentWindow!, "postMessage").mockImplementation(() => {});
      ask(frame, REQUEST);
      expect(dialog()).toBeNull();
      expect(post).not.toHaveBeenCalled();
    });

    it("is never listened for by a thumbnail", () => {
      // Near the viewport at once, so the card loads its page.
      vi.stubGlobal(
        "IntersectionObserver",
        class {
          constructor(private callback: (entries: { isIntersecting: boolean }[]) => void) {}
          observe() {
            this.callback([{ isIntersecting: true }]);
          }
          disconnect() {}
        },
      );
      vi.stubGlobal("ResizeObserver", undefined);
      useArtifactViewMock.mockReturnValue({ ...viewOf(), isError: false });
      const { container } = render(<ArtifactThumbnail artifactId="a1" title="Q3 page" />);
      const frame = container.querySelector("iframe")!;
      const post = vi.spyOn(frame.contentWindow!, "postMessage").mockImplementation(() => {});
      ask(frame, REQUEST);
      expect(dialog()).toBeNull();
      expect(post).not.toHaveBeenCalled();
      vi.unstubAllGlobals();
    });
  });

  describe("which action it means", () => {
    it("rejects a name that is not a declared action, and opens nothing", () => {
      const { frame, rejected } = page();
      ask(frame, { ...REQUEST, action: "Delete everything" });
      expect(dialog()).toBeNull();
      expect(rejected()).toEqual([
        expect.objectContaining({ n: "n1", id: "r1", reason: "unknown_action" }),
      ]);
    });

    it("takes a workflow id, the page's label or the workflow's name", () => {
      const { frame } = page();
      for (const action of ["w2", "tidy", "ARCHIVE DEALS "]) {
        ask(frame, { ...REQUEST, action, input: {} });
        expect(screen.getByRole("heading", { name: "Archive deals" })).toBeInTheDocument();
        fireEvent.click(cancelButton());
      }
    });

    it("answers a label two actions share with neither", () => {
      useArtifactViewMock.mockReturnValue(
        viewOf({ actions: [SEND, { ...TIDY, label: SEND.label }] }),
      );
      const { frame, rejected } = page();
      ask(frame, { ...REQUEST, action: "send it <b>now</b>" });
      expect(dialog()).toBeNull();
      expect(rejected()).toHaveLength(1);
    });

    it("starts under the version the view served, whatever the page says", async () => {
      const post = vi
        .spyOn(apiClient, "post")
        .mockResolvedValue({ run_id: "run1", status: "pending" });
      const { frame } = page();
      await open(frame, { version_id: "v-evil", workflow_id: "w2", versionId: "v-evil" });
      await act(async () => fireEvent.click(runButton()));
      expect(post).toHaveBeenCalledWith("/artifacts/a1/versions/v1/actions/w1/runs", {
        input: { to: "a@b.c" },
      });
    });
  });

  describe("the dialog", () => {
    it("titles it with the workflow's name and quotes the page's own label", () => {
      const { frame } = page();
      ask(frame, REQUEST);
      expect(screen.getByRole("heading", { name: "Send report" })).toBeInTheDocument();
      // The label is page copy: text, in a quote, never markup and never the title.
      expect(screen.getByText("Send it <b>now</b>").tagName).toBe("Q");
      expect(
        screen.getByText(/The page “\u2068Q3 page\u2069” asks to run this workflow as you/),
      ).toBeInTheDocument();
    });

    it("writes out the characters that reorder text in the page's title and the workflow's name", () => {
      useArtifactViewMock.mockReturnValue(viewOf({ actions: [{ ...SEND, name: "Pay\u202Eout" }] }));
      const title = "Q3\u202Eetadpu";
      render(wrapped(<ArtifactFrame artifactId="a1" versionId={null} title={title} />));
      const frame = screen.getByTitle(title) as HTMLIFrameElement;
      fireEvent.load(frame);
      ask(frame, REQUEST);
      // Neither draws as a control: both are written out, and the title sits in its own isolate.
      expect(screen.getByRole("heading", { name: "Pay\\u{202E}out" })).toBeInTheDocument();
      expect(
        screen.getByText(/The page “\u2068Q3\\u\{202E\}etadpu\u2069” asks to run this workflow/),
      ).toBeInTheDocument();
      expect(document.body.textContent).not.toContain("\u202E");
    });

    it("shows every value in full, as text", () => {
      const { frame } = page();
      const long = "x".repeat(3000);
      ask(frame, {
        ...REQUEST,
        input: { to: "<img src=x onerror=alert(1)>", copies: 2 },
      });
      expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
      expect(document.querySelector("img")).toBeNull();
      expect(screen.getByText("Recipient")).toBeInTheDocument();
      expect(screen.getByText("copies")).toBeInTheDocument();
      expect(screen.getByText("2")).toBeInTheDocument();
      fireEvent.click(cancelButton());
      ask(frame, { ...REQUEST, id: "r2", input: { to: long } });
      expect(screen.getByText(long)).toBeInTheDocument();
    });

    it("writes out what cannot be seen and reads each value in its own direction", () => {
      const { frame } = page();
      ask(frame, { ...REQUEST, input: { to: "a\u202Eb\u200Bc" } });
      const value = screen.getByText("a\\u{202E}b\\u{200B}c");
      expect(value.getAttribute("dir")).toBe("auto");
      expect(value.className).toContain("[unicode-bidi:plaintext]");
      expect(screen.getByText("Recipient").getAttribute("dir")).toBe("auto");
      expect(screen.getByText("Send it <b>now</b>").getAttribute("dir")).toBe("auto");
    });

    it("says so when an optional value is not given, and when nothing is sent", () => {
      const { frame } = page();
      ask(frame, { ...REQUEST, input: { to: "a", copies: null } });
      expect(screen.getByText("not given")).toBeInTheDocument();
      fireEvent.click(cancelButton());
      ask(frame, { ...REQUEST, id: "r2", action: "w2", input: {} });
      expect(screen.getByText("Nothing: the workflow takes no input.")).toBeInTheDocument();
    });

    it("keeps Run disabled for half a second, and never focuses it", async () => {
      const { frame } = page();
      ask(frame, REQUEST);
      expect(runButton()).toBeDisabled();
      expect(cancelButton()).toHaveFocus();
      await advance(499);
      expect(runButton()).toBeDisabled();
      await advance(1);
      expect(runButton()).toBeEnabled();
      expect(runButton()).not.toHaveFocus();
      expect(cancelButton()).toHaveFocus();
    });

    it("refuses what the fields do not fit at once: no dialog, no decline spent", () => {
      const { frame, rejected } = page();
      const start = vi.spyOn(apiClient, "post");
      for (let i = 0; i < MAX_CANCELS + 1; i += 1) {
        ask(frame, { ...REQUEST, id: `bad${i}`, input: { copies: 1.5, extra: 1 } });
      }
      expect(dialog()).toBeNull();
      expect(rejected()).toHaveLength(MAX_CANCELS + 1);
      expect(rejected()[0]).toMatchObject({
        id: "bad0",
        reason: "invalid_input",
        problems: [
          { field: "to", kind: "required" },
          { field: "copies", kind: "integer" },
          { field: "extra", kind: "unknown" },
        ],
      });
      expect(start).not.toHaveBeenCalled();
      ask(frame, REQUEST);
      expect(dialog()).not.toBeNull();
    });

    it("stays open while a person clicks inside it", async () => {
      const { frame } = page();
      await open(frame);
      fireEvent.click(screen.getByRole("heading", { name: "Send report" }));
      expect(dialog()).not.toBeNull();
    });
  });

  describe("declining", () => {
    it("rejects the page's promise on Cancel", () => {
      const { frame, rejected } = page();
      ask(frame, REQUEST);
      fireEvent.click(cancelButton());
      expect(dialog()).toBeNull();
      expect(rejected()).toEqual([expect.objectContaining({ id: "r1", reason: "cancelled" })]);
    });

    it("rejects it on Escape", () => {
      const { frame, rejected } = page();
      ask(frame, REQUEST);
      fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
      expect(dialog()).toBeNull();
      expect(rejected()).toEqual([expect.objectContaining({ reason: "cancelled" })]);
    });

    it("lets the first request stand and refuses the next while it is open", () => {
      const { frame, rejected } = page();
      ask(frame, REQUEST);
      ask(frame, { ...REQUEST, id: "r2", input: { to: "someone@else.example" } });
      expect(rejected()).toEqual([expect.objectContaining({ id: "r2", reason: "busy" })]);
      expect(screen.getByText("a@b.c")).toBeInTheDocument();
      expect(screen.queryByText("someone@else.example")).toBeNull();
    });

    it("stops asking after three declines, and a reload of the page does not undo that", () => {
      const { frame, rejected } = page();
      for (let i = 0; i < MAX_CANCELS; i += 1) {
        ask(frame, { ...REQUEST, id: `c${i}` });
        fireEvent.click(cancelButton());
      }
      ask(frame, { ...REQUEST, id: "late" });
      expect(dialog()).toBeNull();
      expect(rejected().at(-1)).toMatchObject({ id: "late", reason: "too_many_cancels" });

      fireEvent.load(frame);
      ask(frame, { ...REQUEST, id: "again" });
      expect(dialog()).toBeNull();
      expect(rejected().at(-1)).toMatchObject({ id: "again", reason: "too_many_cancels" });
    });

    it("counts a decline on the page that was reloaded, and asks again for a new nonce", () => {
      const { frame, rejected, rerender } = page();
      ask(frame, { ...REQUEST, id: "c0" });
      fireEvent.click(cancelButton());
      fireEvent.load(frame);
      for (let i = 1; i < MAX_CANCELS; i += 1) {
        ask(frame, { ...REQUEST, id: `c${i}` });
        fireEvent.click(cancelButton());
      }
      ask(frame, { ...REQUEST, id: "late" });
      expect(rejected().at(-1)).toMatchObject({ id: "late", reason: "too_many_cancels" });

      useArtifactViewMock.mockReturnValue(viewOf({ nonce: "n2" }));
      rerender(wrapped(FRAME));
      fireEvent.load(frame);
      ask(frame, { ...REQUEST, n: "n2", id: "fresh" });
      expect(dialog()).not.toBeNull();
    });

    it("refuses a request before the page has loaded, with no dialog", () => {
      const { frame, rejected } = page(FRAME, false);
      ask(frame, REQUEST);
      expect(dialog()).toBeNull();
      expect(rejected()).toEqual([expect.objectContaining({ id: "r1", reason: "not_ready" })]);
      fireEvent.load(frame);
      ask(frame, REQUEST);
      expect(dialog()).not.toBeNull();
    });

    it("is not ready again for a new nonce until that load", () => {
      const { frame, rejected, rerender } = page();
      useArtifactViewMock.mockReturnValue(viewOf({ nonce: "n2" }));
      rerender(wrapped(FRAME));
      ask(frame, { ...REQUEST, n: "n2" });
      expect(rejected()).toEqual([expect.objectContaining({ reason: "not_ready", n: "n2" })]);
    });

    it("asks about a link or a run, never both: a run is busy while a link is read", () => {
      const { frame, rejected } = page();
      ask(frame, { type: "agenticos:open-link", href: "https://docs.example.com/q3" });
      expect(screen.getByText("https://docs.example.com/q3")).toBeInTheDocument();
      ask(frame, REQUEST);
      expect(rejected()).toEqual([expect.objectContaining({ id: "r1", reason: "busy" })]);
      expect(screen.queryByRole("heading", { name: "Send report" })).toBeNull();
      fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
      ask(frame, { ...REQUEST, id: "r2" });
      expect(screen.getByRole("heading", { name: "Send report" })).toBeInTheDocument();
    });

    it("drops a link request while a run is being asked, and again once it is decided", () => {
      const { frame } = page();
      ask(frame, REQUEST);
      ask(frame, { type: "agenticos:open-link", href: "https://docs.example.com/q3" });
      expect(screen.queryByText("https://docs.example.com/q3")).toBeNull();
      fireEvent.click(cancelButton());
      expect(dialog()).toBeNull();
      ask(frame, { type: "agenticos:open-link", href: "https://docs.example.com/q3" });
      expect(screen.getByText("https://docs.example.com/q3")).toBeInTheDocument();
    });

    it("ends the dialog when the frame loads again, telling the new document nothing", () => {
      const { frame, rejected } = page();
      ask(frame, REQUEST);
      fireEvent.load(frame);
      expect(dialog()).toBeNull();
      // Its first request is `r1` as well: a rejection posted now could answer that one.
      expect(rejected()).toEqual([]);
    });

    it("ends the dialog when another version is served", () => {
      const { frame, rejected, rerender } = page();
      ask(frame, REQUEST);
      useArtifactViewMock.mockReturnValue(
        viewOf({ nonce: "n2", version: { id: "v2" } as ArtifactVersion }),
      );
      rerender(wrapped(FRAME));
      expect(dialog()).toBeNull();
      expect(rejected()).toEqual([expect.objectContaining({ n: "n1", reason: "page_changed" })]);
    });

    it("ends the dialog when the page is closed", () => {
      const { frame, unmount } = page();
      ask(frame, REQUEST);
      unmount();
      expect(dialog()).toBeNull();
    });
  });

  describe("a run the person agreed to", () => {
    const get = () => vi.spyOn(apiClient, "get");
    const progress = (sent: () => Record<string, unknown>[]) =>
      sent().filter((message) => message.event === "progress");

    it("is started, then followed with a growing delay, each change posted to the page", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      const read = get()
        .mockResolvedValueOnce(RUNNING)
        .mockResolvedValueOnce(RUNNING)
        .mockResolvedValue(DONE);
      const { frame, sent } = page();
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      expect(dialog()).toBeNull();
      expect(progress(sent)).toEqual([
        expect.objectContaining({ id: "r1", status: "pending", finished: false }),
      ]);

      await advance(499);
      expect(read).not.toHaveBeenCalled();
      await advance(1);
      expect(read).toHaveBeenCalledWith("/artifacts/a1/actions/runs/run1");
      expect(progress(sent)).toHaveLength(2);
      // The delay grows: 500, then 750. An unchanged read is not posted again.
      await advance(749);
      expect(read).toHaveBeenCalledTimes(1);
      await advance(1);
      expect(read).toHaveBeenCalledTimes(2);
      expect(progress(sent)).toHaveLength(2);
      await advance(1125);
      expect(progress(sent).at(-1)).toMatchObject({
        status: "completed",
        finished: true,
        output_text: "Sent",
      });

      await advance(60_000);
      expect(read).toHaveBeenCalledTimes(3);
    });

    it("tells the page a run waits on someone, and lists it for the person", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      const path = "/workflows/w1/runs/run1?org=o1";
      get()
        .mockResolvedValueOnce({ ...RUNNING, status: "waiting", paused: true, run_path: path })
        .mockResolvedValue(DONE);
      let bridge: DataBridge | null = null;
      const { frame, sent } = page(
        <ArtifactFrame
          artifactId="a1"
          versionId={null}
          title="Q3 page"
          onBridge={(lent) => (bridge = lent)}
        />,
      );
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      await advance(500);
      expect(sent().at(-1)).toMatchObject({ paused: true, run_path: path });
      expect((bridge as DataBridge | null)?.paused).toEqual([
        { runId: "run1", name: "Send report", path },
      ]);

      await advance(750);
      expect((bridge as DataBridge | null)?.paused).toEqual([]);
    });

    describe("a run that stays paused", () => {
      const waiting = {
        ...RUNNING,
        status: "waiting",
        paused: true,
        run_path: "/workflows/w1/runs/r",
      };
      const setHidden = (hidden: boolean) =>
        Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
      afterEach(() => setHidden(false));

      async function started() {
        vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
        const read = get().mockResolvedValue(waiting);
        const { frame, sent } = page();
        await open(frame);
        await act(async () => fireEvent.click(runButton()));
        return Object.assign(read, { sent });
      }

      it("is read for ten minutes and then left alone", async () => {
        const read = await started();
        await advance(11 * 60 * 1000);
        const reads = read.mock.calls.length;
        expect(reads).toBeGreaterThan(100);
        await advance(5 * 60 * 1000);
        expect(read).toHaveBeenCalledTimes(reads);
      });

      it("tells the page, once, the run is left alone, so its promise settles", async () => {
        const { sent } = await started();
        await advance(11 * 60 * 1000);
        const settled = sent().filter((m) => (m as { settled?: boolean }).settled);
        expect(settled).toHaveLength(1);
        expect(settled[0]).toMatchObject({ finished: false, paused: true, status: "waiting" });
        await advance(5 * 60 * 1000);
        expect(sent().filter((m) => (m as { settled?: boolean }).settled)).toHaveLength(1);
      });

      it("is not read while the tab is hidden, and is again once it shows", async () => {
        const read = await started();
        await advance(500);
        setHidden(true);
        await advance(60_000);
        const reads = read.mock.calls.length;
        document.dispatchEvent(new Event("visibilitychange"));
        await advance(60_000);
        expect(read).toHaveBeenCalledTimes(reads);
        setHidden(false);
        document.dispatchEvent(new Event("visibilitychange"));
        await advance(10_000);
        expect(read.mock.calls.length).toBeGreaterThan(reads);
      });

      it("does not come back to a page that loaded again while it was hidden", async () => {
        const read = await started();
        await advance(500);
        setHidden(true);
        await advance(1000);
        const reads = read.mock.calls.length;
        fireEvent.load(screen.getByTitle("Q3 page"));
        setHidden(false);
        document.dispatchEvent(new Event("visibilitychange"));
        await advance(10_000);
        expect(read).toHaveBeenCalledTimes(reads);
      });
    });

    it("forgets a waiting run when the page loads again", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      get().mockResolvedValue({
        ...RUNNING,
        paused: true,
        run_path: "/workflows/w1/runs/run1",
      });
      let bridge: DataBridge | null = null;
      const { frame } = page(
        <ArtifactFrame
          artifactId="a1"
          versionId={null}
          title="Q3 page"
          onBridge={(lent) => (bridge = lent)}
        />,
      );
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      await advance(500);
      expect((bridge as DataBridge | null)?.paused).toHaveLength(1);
      fireEvent.load(frame);
      expect((bridge as DataBridge | null)?.paused).toEqual([]);
    });

    it("never lists a link that is not a console path", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      get().mockResolvedValue({
        ...RUNNING,
        paused: true,
        run_path: "https://evil.example/workflows/w1/runs/r",
      });
      let bridge: DataBridge | null = null;
      const { frame } = page(
        <ArtifactFrame
          artifactId="a1"
          versionId={null}
          title="Q3 page"
          onBridge={(lent) => (bridge = lent)}
        />,
      );
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      await advance(500);
      expect((bridge as DataBridge | null)?.paused).toEqual([]);
    });

    it("forwards a failed run's short error", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      get().mockResolvedValue({
        ...DONE,
        status: "failed",
        output_text: null,
        error_message: "The mail server refused it",
      });
      const { frame, sent } = page();
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      await advance(500);
      expect(sent().at(-1)).toMatchObject({
        status: "failed",
        finished: true,
        error_message: "The mail server refused it",
      });
    });

    it("gives up on a run it cannot read, three failures in a row", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      const read = get().mockRejectedValue(new Error("offline"));
      const { frame, rejected } = page();
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      await advance(500 + 750);
      expect(rejected()).toEqual([]);
      await advance(1125);
      expect(rejected()).toEqual([expect.objectContaining({ id: "r1", reason: "failed" })]);
      await advance(60_000);
      expect(read).toHaveBeenCalledTimes(3);
    });

    it("says nothing for a read that comes back after the frame loaded again", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      let settle: (run: ArtifactActionRun) => void = () => {};
      get().mockReturnValue(
        new Promise((resolve) => {
          settle = resolve;
        }),
      );
      const { frame, sent } = page();
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      await advance(500);
      fireEvent.load(frame);
      await act(async () => settle(DONE));
      expect(sent()).toEqual([expect.objectContaining({ status: "pending" })]);
    });

    it("keeps following after one read that failed", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      get().mockRejectedValueOnce(new Error("blip")).mockResolvedValue(DONE);
      const { frame, sent, rejected } = page();
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      await advance(500 + 750);
      expect(rejected()).toEqual([]);
      expect(sent().at(-1)).toMatchObject({ finished: true });
    });

    it("stops following when the frame loads again", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      const read = get().mockResolvedValue(RUNNING);
      const { frame } = page();
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      await advance(500);
      expect(read).toHaveBeenCalledTimes(1);
      fireEvent.load(frame);
      await advance(60_000);
      expect(read).toHaveBeenCalledTimes(1);
    });

    it("stops following when the page is closed", async () => {
      vi.spyOn(apiClient, "post").mockResolvedValue({ run_id: "run1", status: "pending" });
      const read = get().mockResolvedValue(RUNNING);
      const { frame, unmount } = page();
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      unmount();
      await advance(60_000);
      expect(read).not.toHaveBeenCalled();
    });

    it("says nothing to a page that reloaded while the start was in flight", async () => {
      let settle: (value: { run_id: string; status: string }) => void = () => {};
      vi.spyOn(apiClient, "post").mockReturnValue(
        new Promise((resolve) => {
          settle = resolve;
        }),
      );
      const read = get().mockResolvedValue(RUNNING);
      const { frame, sent } = page();
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      fireEvent.load(frame);
      await act(async () => settle({ run_id: "run1", status: "pending" }));
      await advance(60_000);
      expect(sent()).toEqual([]);
      expect(read).not.toHaveBeenCalled();
    });
  });

  describe("a start the server refused", () => {
    async function refused(error: unknown) {
      vi.spyOn(apiClient, "post").mockRejectedValue(error);
      const view = page();
      await open(view.frame);
      await act(async () => fireEvent.click(runButton()));
      return view;
    }

    it("on a limit: a toast for the person, and a short reason for the page", async () => {
      const { rejected } = await refused(new ApiError(429, "slow down"));
      expect(toastError).toHaveBeenCalledWith(
        "Too many runs from this page. Try again in a minute.",
      );
      expect(rejected()).toEqual([expect.objectContaining({ reason: "rate_limited" })]);
    });

    it("on an input the workflow refuses: the page is told, with no toast", async () => {
      const { rejected } = await refused(new ApiError(422, "bad input"));
      expect(toastError).not.toHaveBeenCalled();
      expect(rejected()).toEqual([expect.objectContaining({ reason: "invalid_input" })]);
    });

    it("on an action that is gone: the page is told, with no toast", async () => {
      const { rejected } = await refused(new ApiError(404, "nope"));
      expect(toastError).not.toHaveBeenCalled();
      expect(rejected()).toEqual([expect.objectContaining({ reason: "not_found" })]);
    });

    it("on a workflow that no longer starts by hand: a toast, and the page is told", async () => {
      const { rejected } = await refused(new ApiError(409, "archived"));
      expect(toastError).toHaveBeenCalledTimes(1);
      expect(rejected()).toEqual([expect.objectContaining({ reason: "unavailable" })]);
    });

    it("on anything else: a toast, and a plain failure for the page", async () => {
      const { rejected } = await refused(new Error("network"));
      expect(toastError).toHaveBeenCalledTimes(1);
      expect(rejected()).toEqual([expect.objectContaining({ reason: "failed" })]);
    });

    it("says nothing to a page that reloaded before the refusal came", async () => {
      let fail: (error: unknown) => void = () => {};
      vi.spyOn(apiClient, "post").mockReturnValue(
        new Promise((_, reject) => {
          fail = reject;
        }),
      );
      const { frame, sent } = page();
      await open(frame);
      await act(async () => fireEvent.click(runButton()));
      fireEvent.load(frame);
      await act(async () => fail(new ApiError(429, "slow")));
      expect(sent()).toEqual([]);
      expect(toastError).not.toHaveBeenCalled();
    });
  });
});

describe("the controller on its own", () => {
  beforeEach(() => {
    useArtifactViewMock.mockReturnValue(viewOf());
  });

  afterEach(() => vi.restoreAllMocks());

  const ACTIONS = [SEND];

  function controller() {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const ref = { current: frame };
    const gate = renderHook(() => useAskingGate()).result.current;
    const view = renderHook(
      () =>
        useArtifactActions({
          artifactId: "a1",
          frame: ref,
          nonce: "n1",
          versionId: "v1",
          enabled: true,
          actions: ACTIONS,
          asking: gate,
        }),
      { wrapper: ({ children }) => wrapped(<>{children}</>) },
    );
    act(() => view.result.current.onLoad());
    return { ...view, frame, gate };
  }

  it("has nothing to decline or confirm until a page asks", async () => {
    const start = vi.spyOn(apiClient, "post");
    const { result } = controller();
    act(() => result.current.cancel());
    await act(async () => result.current.confirm());
    expect(start).not.toHaveBeenCalled();
    expect(result.current.pending).toBeNull();
  });

  it("opens nothing for a request that does not fit the action", () => {
    const { result, frame } = controller();
    ask(frame, { ...REQUEST, input: {} });
    expect(result.current.pending).toBeNull();
  });

  it("is busy while another question holds the gate, and takes it while it asks", () => {
    const { result, frame, gate } = controller();
    gate.take("link");
    ask(frame, REQUEST);
    expect(result.current.pending).toBeNull();
    gate.release("link");
    ask(frame, REQUEST);
    expect(result.current.pending).not.toBeNull();
    expect(gate.held()).toBe("run");
    act(() => result.current.cancel());
    expect(gate.held()).toBeNull();
  });
});
