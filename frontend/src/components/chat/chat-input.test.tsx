import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { toast } from "sonner";

import { messageOf } from "./composer-editor";
import { ChatInput, type ComposerDictation } from "./chat-input";
import type { DictationState } from "@/hooks/use-dictation";
import { useChatStore } from "@/stores";
import { PublicConfigProvider } from "@/components/public-config/public-config-provider";
import type { FileUploadResponse } from "@/lib/file-api";
import { DEFAULT_PUBLIC_CONFIG } from "@/lib/public-config";

const state = vi.hoisted(() => ({
  upload: vi.fn<(file: File) => Promise<FileUploadResponse>>(),
}));

vi.mock("@/lib/file-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/file-api")>()),
  uploadFile: (file: File) => state.upload(file),
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn() } }));
// The `@` menu's request; `chat-input.mentions.test.tsx` drives it.
vi.mock("@/hooks/use-mentionables", () => ({
  useMentionables: () => ({ items: [], isLoading: false, isError: false }),
}));

vi.mock("next/image", () => ({
  // eslint-disable-next-line @next/next/no-img-element
  default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} />,
}));

function uploaded(overrides: Partial<FileUploadResponse> = {}): FileUploadResponse {
  return {
    id: "f-1",
    filename: "pasted-2026-08-08.txt",
    mime_type: "text/plain",
    size: 50_000,
    file_type: "text",
    preview: "Traceback (most recent call last):",
    ...overrides,
  };
}

const LONG = "x".repeat(50_000);
const CHAT_MAX_UPLOAD_SIZE_MB = DEFAULT_PUBLIC_CONFIG.chatMaxUploadSizeMb;

beforeEach(() => {
  state.upload.mockReset();
  state.upload.mockResolvedValue(uploaded());
  // The toast mock is module-level, so without this a refusal asserted in one
  // test is still recorded in the next one that asserts none.
  vi.mocked(toast.error).mockClear();
  vi.mocked(toast.info).mockClear();
});

describe("ChatInput replying", () => {
  it("says what the next turn answers, and lets it be taken back", async () => {
    act(() =>
      useChatStore
        .getState()
        .setReplyTo({ messageId: "m-2", role: "assistant", excerpt: "Plan: A, B" }),
    );
    render(<ChatInput onSend={vi.fn()} />);
    expect(screen.getByText("The agent")).toBeInTheDocument();
    expect(screen.getByText("Plan: A, B")).toBeInTheDocument();
    // Ready to type the answer.
    expect(screen.getByRole("textbox")).toHaveFocus();

    await userEvent.click(screen.getByRole("button", { name: "Don't reply" }));
    expect(useChatStore.getState().replyTo).toBeNull();
    expect(screen.queryByText("Plan: A, B")).toBeNull();
  });
});

describe("ChatInput typing", () => {
  it("says the person is writing when they type words, not when they clear the box", async () => {
    const onTyping = vi.fn();
    render(<ChatInput onSend={vi.fn()} onTyping={onTyping} />);

    await userEvent.type(screen.getByRole("textbox"), "hi");
    expect(onTyping).toHaveBeenCalledTimes(2);

    await userEvent.clear(screen.getByRole("textbox"));
    expect(onTyping).toHaveBeenCalledTimes(2);
  });

  it("says when the box holds words of the person's own, and when it no longer does", async () => {
    // What hides the latest answer's next steps from the composer (#2301).
    const onDraftChange = vi.fn();
    render(<ChatInput onSend={vi.fn()} onDraftChange={onDraftChange} />);
    expect(onDraftChange).toHaveBeenLastCalledWith(false);

    await userEvent.type(screen.getByRole("textbox"), "hi");
    expect(onDraftChange).toHaveBeenLastCalledWith(true);

    await userEvent.clear(screen.getByRole("textbox"));
    expect(onDraftChange).toHaveBeenLastCalledWith(false);
  });
});

describe("ChatInput offline", () => {
  it("says it is reconnecting where it would ask for a message (#2301)", () => {
    render(<ChatInput onSend={vi.fn()} offline disabled />);

    expect(screen.getByText("Reconnecting…")).toBeInTheDocument();
  });
});

describe("ChatInput idle slot", () => {
  it("offers the call in Send's place until there is something to send (#2301)", async () => {
    render(
      <ChatInput
        onSend={vi.fn()}
        idleSlot={
          <button type="button" aria-label="Start a call">
            call
          </button>
        }
      />,
    );
    expect(screen.getByRole("button", { name: "Start a call" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send message" })).toBeNull();

    await userEvent.type(screen.getByRole("textbox"), "hi");

    expect(screen.getByRole("button", { name: "Send message" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start a call" })).toBeNull();
  });
});

describe("ChatInput paste", () => {
  it("turns a long paste into an attachment and leaves the composer empty", async () => {
    // The point of the whole feature: the question somebody is about to type has
    // to still fit on the screen after they paste the thing it is about.
    render(<ChatInput onSend={vi.fn()} />);
    const box = screen.getByRole("textbox");

    await userEvent.click(box);
    await userEvent.paste(LONG);

    expect(await screen.findByText("pasted-2026-08-08.txt")).toBeVisible();
    expect(screen.getByText("Pasted · 48.8 KB")).toBeVisible();
    expect(messageOf(box)).toBe("");
  });

  it("uploads the paste as a text file, which is what the agent can then read", async () => {
    render(<ChatInput onSend={vi.fn()} />);

    await userEvent.click(screen.getByRole("textbox"));
    await userEvent.paste(LONG);

    await waitFor(() => expect(state.upload).toHaveBeenCalledOnce());
    const file = state.upload.mock.calls[0]![0];
    expect(file.type).toBe("text/plain");
    expect(file.name).toMatch(/^pasted-\d{4}-\d{2}-\d{2}\.txt$/);
    expect(await file.text()).toBe(LONG);
  });

  it("attaches a pasted picture, which Ctrl+V used to drop", async () => {
    state.upload.mockResolvedValue(
      uploaded({ filename: "image.png", mime_type: "image/png", file_type: "image", size: 4 }),
    );
    render(<ChatInput onSend={vi.fn()} />);
    const box = screen.getByRole("textbox");
    const picture = new File([new Uint8Array([137, 80, 78, 71])], "image.png", {
      type: "image/png",
    });

    await userEvent.click(box);
    await userEvent.paste({
      files: [picture],
      items: [],
      getData: () => "",
      types: ["Files"],
    } as unknown as DataTransfer);

    await waitFor(() => expect(state.upload).toHaveBeenCalledOnce());
    expect(state.upload.mock.calls[0]![0]).toBe(picture);
    expect(messageOf(box)).toBe("");
  });

  it("leaves a short paste alone - somebody who pastes a paragraph meant to send it", async () => {
    render(<ChatInput onSend={vi.fn()} />);
    const box = screen.getByRole("textbox");

    await userEvent.click(box);
    await userEvent.paste("what does this error mean?");

    expect(messageOf(box)).toBe("what does this error mean?");
    expect(state.upload).not.toHaveBeenCalled();
  });

  it("sends the attachment with the question typed beside it", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const box = screen.getByRole("textbox");

    await userEvent.click(box);
    await userEvent.paste(LONG);
    await screen.findByText("pasted-2026-08-08.txt");
    await userEvent.type(box, "why does this fail?");
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("why does this fail?", ["f-1"], [uploaded()], undefined);
  });
});

/**
 * A `FileList` that empties *in place* when the input is reset, as Blink's does.
 *
 * This is the one browser behaviour this suite cannot get from jsdom, and the
 * reason the picker shipped broken with every test here green: jsdom hands the
 * input a fresh list on reset, so a handler that captures `input.files` and
 * *then* sets `input.value = ""` still sees a populated list under test and an
 * empty one in Chrome, Edge and Safari. Modelled rather than trusted.
 */
function blinkFileList(...files: File[]): FileList {
  const list = {
    length: files.length,
    item: (index: number): File | null => files[index] ?? null,
    clear(): void {
      this.length = 0;
    },
    *[Symbol.iterator](): Generator<File> {
      for (let index = 0; index < this.length; index++) yield files[index]!;
    },
  };
  files.forEach((file, index) => Object.defineProperty(list, index, { value: file }));
  // A test double for a host object with no constructor reachable from script.
  return list as unknown as FileList;
}

/** Wire `input.value = ""` to clear `input.files` in place, the way a browser does. */
function pick(input: HTMLInputElement, ...files: File[]): void {
  const list = blinkFileList(...files);
  Object.defineProperty(input, "files", { configurable: true, get: () => list });
  Object.defineProperty(input, "value", {
    configurable: true,
    get: () => "",
    set: () => (list as unknown as { clear: () => void }).clear(),
  });
  fireEvent.change(input);
}

describe("ChatInput attachments", () => {
  it("uploads a file picked through the paperclip, having copied it before resetting the input", async () => {
    // The picker was dead on every real browser: the handler kept the input's
    // own live `FileList`, reset the input - which empties that same object -
    // and only then read it, so `Array.from` saw nothing and the upload
    // returned at its empty guard. No card, no toast, no request, nothing in
    // either service's logs. Drag-and-drop and paste were unaffected, because
    // neither goes through the input.
    state.upload.mockResolvedValue(uploaded({ filename: "notes.txt", size: 2 }));
    const { container } = render(<ChatInput onSend={vi.fn()} />);

    pick(
      container.querySelector<HTMLInputElement>('input[type="file"]')!,
      new File(["hi"], "notes.txt", { type: "text/plain" }),
    );

    await waitFor(() => expect(state.upload).toHaveBeenCalledOnce());
    expect(state.upload.mock.calls[0]![0].name).toBe("notes.txt");
    expect(await screen.findByText("notes.txt")).toBeVisible();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("shows a card per queued file while it uploads, not one box beside the finished ones", async () => {
    let answer: (file: FileUploadResponse) => void = () => {};
    state.upload.mockImplementation(
      () => new Promise<FileUploadResponse>((resolve) => (answer = resolve)),
    );
    const { container } = render(<ChatInput onSend={vi.fn()} />);

    await userEvent.upload(
      container.querySelector<HTMLInputElement>('input[type="file"]')!,
      new File(["column,value"], "data.csv", { type: "text/csv" }),
    );

    expect(await screen.findByText("data.csv")).toBeVisible();
    expect(screen.getByText("Uploading · 12 B")).toBeVisible();

    answer(uploaded({ filename: "data.csv", size: 12, preview: "column,value" }));

    expect(await screen.findByText("CSV · 12 B")).toBeVisible();
    expect(screen.queryByText(/Uploading/)).toBeNull();
  });

  it("keeps twenty attachments on one scrolling row", async () => {
    // #927. They were a wrapping grid of 224px tiles: six files were two rows and
    // twenty were seven, about 850px of composer, with the message box below the
    // fold. This assertion fails if somebody restores the wrap.
    const { container } = render(<ChatInput onSend={vi.fn()} />);
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;

    for (let n = 0; n < 20; n++) {
      state.upload.mockResolvedValueOnce(uploaded({ filename: `report-${n}.csv`, size: 12 }));
    }
    await userEvent.upload(
      input,
      Array.from(
        { length: 20 },
        (_, n) => new File(["a,b"], `report-${n}.csv`, { type: "text/csv" }),
      ),
    );

    expect(await screen.findByText("report-19.csv")).toBeVisible();
    expect(screen.getByText("20 files")).toBeVisible();

    const row = screen.getByText("report-19.csv").closest(".overflow-x-auto");

    expect(row).not.toBeNull();
    expect(row!.className).not.toMatch(/flex-wrap/);
  });

  it("removes an attachment without needing a hover first", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    await userEvent.click(screen.getByRole("textbox"));
    await userEvent.paste(LONG);

    await userEvent.click(
      await screen.findByRole("button", { name: "Remove pasted-2026-08-08.txt" }),
    );

    expect(screen.queryByText("pasted-2026-08-08.txt")).toBeNull();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });
  it("refuses a file over the chat ceiling without uploading it", async () => {
    // #498. The composer checked against a default of 50MB while the server
    // refused at 10, so a 20MB file passed here, was read, was sent in full and
    // came back refused by a number no configuration held. The client's ceiling
    // is the chat surface's own now, not the knowledge base's.
    const { container } = render(<ChatInput onSend={vi.fn()} />);

    await userEvent.upload(
      container.querySelector<HTMLInputElement>('input[type="file"]')!,
      new File([new Uint8Array(CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1)], "export.csv", {
        type: "text/csv",
      }),
    );

    expect(toast.error).toHaveBeenCalledWith(
      `export.csv: File too large. Maximum ${CHAT_MAX_UPLOAD_SIZE_MB}MB.`,
    );
    expect(state.upload).not.toHaveBeenCalled();
    expect(screen.queryByText("export.csv")).toBeNull();
  });

  it("accepts a file at the ceiling, so the boundary is not off by one", async () => {
    const atLimit = CHAT_MAX_UPLOAD_SIZE_MB * 1024 * 1024;
    state.upload.mockResolvedValue(uploaded({ filename: "atlimit.csv", size: atLimit }));
    const { container } = render(<ChatInput onSend={vi.fn()} />);

    await userEvent.upload(
      container.querySelector<HTMLInputElement>('input[type="file"]')!,
      new File([new Uint8Array(atLimit)], "atlimit.csv", { type: "text/csv" }),
    );

    expect(await screen.findByText("atlimit.csv")).toBeVisible();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("takes the ceiling from the deployment, not from the build (#1544)", async () => {
    // One published image serves every deployment, so the number the composer
    // refuses at is the running server's `CHAT_MAX_UPLOAD_SIZE_MB`, handed down
    // through the public-config context rather than inlined at build time.
    const { container } = render(
      <PublicConfigProvider config={{ ...DEFAULT_PUBLIC_CONFIG, chatMaxUploadSizeMb: 1 }}>
        <ChatInput onSend={vi.fn()} />
      </PublicConfigProvider>,
    );

    await userEvent.upload(
      container.querySelector<HTMLInputElement>('input[type="file"]')!,
      new File([new Uint8Array(1024 * 1024 + 1)], "export.csv", { type: "text/csv" }),
    );

    expect(toast.error).toHaveBeenCalledWith("export.csv: File too large. Maximum 1MB.");
    expect(state.upload).not.toHaveBeenCalled();
  });

  it("attaches files handed in from outside once per hand-off, as if picked", async () => {
    // The AI Architect's screenshot of the page arrives this way (#2063).
    const shot = new File(["png"], "screenshot.png", { type: "image/png" });
    const { rerender } = render(<ChatInput onSend={vi.fn()} incoming={{ id: 1, files: [shot] }} />);
    await waitFor(() => expect(state.upload).toHaveBeenCalledWith(shot));

    rerender(<ChatInput onSend={vi.fn()} incoming={{ id: 1, files: [shot] }} />);
    rerender(<ChatInput onSend={vi.fn()} incoming={{ id: 2, files: [shot] }} />);

    await waitFor(() => expect(state.upload).toHaveBeenCalledTimes(2));
  });

  it("writes words handed in after what is already typed", async () => {
    // A comment pointed at the browser's page arrives with its note.
    const shot = new File(["png"], "browser-comment.png", { type: "image/png" });
    const { rerender } = render(<ChatInput onSend={vi.fn()} />);
    await userEvent.type(screen.getByRole("textbox"), "Two things.");

    rerender(
      <ChatInput onSend={vi.fn()} incoming={{ id: 1, files: [shot], text: "This button" }} />,
    );

    await waitFor(() =>
      expect(messageOf(screen.getByRole("textbox"))).toBe("Two things.\nThis button"),
    );
    rerender(<ChatInput onSend={vi.fn()} incoming={{ id: 2, files: [shot], text: "And this" }} />);
    await waitFor(() =>
      expect(messageOf(screen.getByRole("textbox"))).toBe("Two things.\nThis button\nAnd this"),
    );
  });

  it("starts the message with words handed in to an empty box", async () => {
    render(<ChatInput onSend={vi.fn()} incoming={{ id: 1, files: [], text: "This button" }} />);

    await waitFor(() => expect(messageOf(screen.getByRole("textbox"))).toBe("This button"));
  });

  it("sends on Enter at a desk, and starts a new line on a touch keyboard", async () => {
    // A phone's keyboard has no Shift to hold for a line break, and the send
    // button is a thumb away (#2066).
    const onSend = vi.fn();
    const { unmount } = render(<ChatInput onSend={onSend} />);
    const box = screen.getByRole("textbox");
    expect(box).toHaveAttribute("enterkeyhint", "send");
    await userEvent.type(box, "hi{Enter}");
    expect(onSend).toHaveBeenCalledOnce();
    unmount();

    const desk = window.matchMedia;
    window.matchMedia = ((query: string) => ({ matches: true, media: query })) as never;
    onSend.mockClear();
    render(<ChatInput onSend={onSend} />);
    const touch = screen.getByRole("textbox");
    expect(touch).toHaveAttribute("enterkeyhint", "enter");
    await userEvent.type(touch, "one{Enter}two");
    expect(onSend).not.toHaveBeenCalled();
    expect(messageOf(touch)).toBe("one\ntwo");
    window.matchMedia = desk;
  });

  it("starts a command from the `+`, the same as typing a slash", async () => {
    const context = { clearChat: vi.fn(), regenerateLast: vi.fn(), openSettings: vi.fn() };
    render(<ChatInput onSend={vi.fn()} slashContext={context} />);

    await userEvent.click(screen.getAllByRole("button", { name: "Add to message" })[0]!);
    await userEvent.click(await screen.findByRole("menuitem", { name: /Commands/ }));

    const box = screen.getByRole("textbox");
    expect(messageOf(box)).toBe("/");
    expect(box).toHaveFocus();
  });
});

function dictationState(overrides: Partial<DictationState> = {}): DictationState {
  return {
    phase: "idle",
    elapsed: 0,
    remaining: null,
    silent: false,
    meter: { read: () => 0, subscribe: () => () => {} },
    reason: null,
    canRetry: false,
    retryAfter: null,
    transcript: null,
    upload: null,
    stoppedAtLimit: false,
    inserted: false,
    ...overrides,
  };
}

/** The page's half of server dictation: plain state, and actions to watch. */
function serverDictation(
  overrides: Partial<Omit<ComposerDictation, "state">> = {},
  state: Partial<DictationState> = {},
): ComposerDictation {
  return {
    engine: "server",
    state: dictationState(state),
    actions: {
      start: vi.fn(async () => {}),
      stop: vi.fn(),
      cancel: vi.fn(),
      retry: vi.fn(),
      dismiss: vi.fn(),
      dismissInserted: vi.fn(),
    },
    ...overrides,
  };
}

/** The same dictation, a step further on. */
function moved(dictation: ComposerDictation, state: Partial<DictationState>): ComposerDictation {
  return { ...dictation, state: { ...dictation.state, ...state } };
}

/** Open the `+` and pick Voice input, which is where dictation starts now. */
async function pressDictate(): Promise<void> {
  await userEvent.click(screen.getAllByRole("button", { name: "Add to message" })[0]!);
  await userEvent.click(await screen.findByRole("menuitem", { name: /Voice input/ }));
}

/** Put the selection `from`-`to` characters into the editor's text. */
function select(box: HTMLElement, from: number, to = from): void {
  const text = box.firstChild!;
  const range = document.createRange();
  range.setStart(text, from);
  range.setEnd(text, to);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
}

/** Where the caret is in the editor's text. */
function caretOf(box: HTMLElement): number {
  const selection = window.getSelection()!;
  const range = document.createRange();
  range.setStart(box, 0);
  range.setEnd(selection.focusNode!, selection.focusOffset);
  return range.toString().length;
}

describe("ChatInput dictation engines", () => {
  it("keeps the browser's own speech recognition for the browser engine", async () => {
    render(<ChatInput onSend={vi.fn()} dictation={serverDictation({ engine: "browser" })} />);

    await pressDictate();

    // jsdom has no Web Speech API: the browser engine's own refusal, unchanged.
    expect(toast.info).toHaveBeenCalledWith(
      "Voice input is only supported in Chrome. Use Chrome for speech-to-text.",
    );
  });

  it("starts recording on the server engine from the `+`", async () => {
    const dictation = serverDictation();
    render(<ChatInput onSend={vi.fn()} dictation={dictation} />);

    await pressDictate();

    expect(dictation.actions.start).toHaveBeenCalledOnce();
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("shows the microphone beside Send whichever engine dictates", async () => {
    const dictation = serverDictation();
    const { rerender } = render(<ChatInput onSend={vi.fn()} dictation={dictation} />);

    await userEvent.click(screen.getByRole("button", { name: "Voice input" }));
    expect(dictation.actions.start).toHaveBeenCalledOnce();

    rerender(<ChatInput onSend={vi.fn()} dictation={serverDictation({ engine: "browser" })} />);
    await userEvent.click(screen.getByRole("button", { name: "Voice input" }));
    expect(toast.info).toHaveBeenCalledWith(
      "Voice input is only supported in Chrome. Use Chrome for speech-to-text.",
    );
  });
});

describe("ChatInput listening in the browser", () => {
  it("hands the page one stop for a recognition, however often the microphone object changes", async () => {
    class FakeRecognition {
      start = vi.fn();
      stop = vi.fn();
    }
    vi.stubGlobal("SpeechRecognition", FakeRecognition);
    // `useMicrophone` answers a new object on every render, and so does this.
    const micOf = () => ({
      stream: null,
      state: "idle" as const,
      error: null,
      supported: true,
      start: vi.fn(async () => null),
      stop: vi.fn(),
    });
    const onListeningChange = vi.fn();
    const draw = () => (
      <ChatInput
        onSend={vi.fn()}
        dictation={serverDictation({ engine: "browser" })}
        mic={micOf()}
        onListeningChange={onListeningChange}
      />
    );
    const { rerender } = render(draw());
    await userEvent.click(screen.getByRole("button", { name: "Voice input" }));
    for (let i = 0; i < 5; i += 1) rerender(draw());

    const stops = onListeningChange.mock.calls.map(([stop]) => stop).filter(Boolean);
    expect(new Set(stops).size).toBe(1);
    vi.unstubAllGlobals();
  });
});

describe("ChatInput while dictating", () => {
  it.each(["recording", "transcribing"] as const)(
    "while %s the box is read-only and nothing can be sent",
    async (phase) => {
      const onSend = vi.fn();
      const dictation = serverDictation();
      const { rerender, container } = render(
        <ChatInput
          onSend={onSend}
          dictation={dictation}
          isProcessing
          onStop={vi.fn()}
          controlsSlot={<span data-testid="agent-picker" />}
        />,
      );
      const box = screen.getByRole("textbox");
      await userEvent.type(box, "draft");

      const busy = moved(dictation, { phase });
      rerender(
        <ChatInput
          onSend={onSend}
          dictation={busy}
          isProcessing
          onStop={vi.fn()}
          controlsSlot={<span data-testid="agent-picker" />}
        />,
      );

      expect(box).toHaveAttribute("aria-readonly", "true");
      expect(box).toHaveAttribute("contenteditable", "false");
      fireEvent.keyDown(box, { key: "Enter" });
      fireEvent.submit(container.querySelector("form")!);
      expect(onSend).not.toHaveBeenCalled();
      expect(busy.actions.stop).toHaveBeenCalledTimes(phase === "recording" ? 1 : 0);
      // The row with the picker, stop-generating and Send stays on screen, inert:
      // the composer does not change under the page's dictation pill.
      expect(screen.getByTestId("agent-picker").closest("[inert]")).not.toBeNull();
      expect(
        screen.getByRole("button", { name: "Stop generating" }).closest("[inert]"),
      ).not.toHaveClass("hidden");

      fireEvent.keyDown(box, { key: "Escape" });
      expect(busy.actions.cancel).toHaveBeenCalledOnce();
      expect(messageOf(box)).toBe("draft");
    },
  );
  it("brings focus back to the box when dictation ends in a failure", () => {
    const dictation = serverDictation({}, { phase: "requesting" });
    const { rerender } = render(<ChatInput onSend={vi.fn()} dictation={dictation} />);
    const step = (state: Partial<DictationState>) =>
      rerender(<ChatInput onSend={vi.fn()} dictation={moved(dictation, state)} />);
    step({ phase: "recording" });
    step({ phase: "transcribing" });

    step({ phase: "failed", reason: "provider_error", canRetry: true });

    expect(screen.getByRole("textbox")).toHaveFocus();
  });

  it("announces each step once, politely", () => {
    const dictation = serverDictation();
    const { rerender, container } = render(<ChatInput onSend={vi.fn()} dictation={dictation} />);
    const status = container.querySelector('[role="status"][aria-live="polite"]')!;
    const step = (state: Partial<DictationState>) =>
      rerender(<ChatInput onSend={vi.fn()} dictation={moved(dictation, state)} />);

    step({ phase: "recording" });
    expect(status).toHaveTextContent("Recording");
    step({ phase: "recording", remaining: 30 });
    expect(status).toHaveTextContent("30 seconds left");
    step({ phase: "recording", remaining: 29 });
    expect(status).toHaveTextContent("30 seconds left");
    step({ phase: "transcribing" });
    expect(status).toHaveTextContent("Transcribing");
    step({ phase: "failed" });
    expect(status).toHaveTextContent("Transcribing");
  });
});

describe("ChatInput inserting a transcript", () => {
  /** Type, put the caret or selection somewhere, press Dictate, and get the box back. */
  async function dictateInto(
    typed: string,
    selection: [number, number] | null,
    text: string,
  ): Promise<HTMLElement> {
    const dictation = serverDictation();
    const { rerender } = render(<ChatInput onSend={vi.fn()} dictation={dictation} />);
    const box = screen.getByRole("textbox");
    if (typed) await userEvent.type(box, typed);
    if (selection) select(box, ...selection);
    await pressDictate();

    rerender(
      <ChatInput onSend={vi.fn()} dictation={moved(dictation, { phase: "transcribing" })} />,
    );
    const done = moved(dictation, { phase: "idle", transcript: { id: 1, text } });
    rerender(<ChatInput onSend={vi.fn()} dictation={done} />);
    // The same transcript again is not a second insertion.
    rerender(<ChatInput onSend={vi.fn()} dictation={{ ...done }} />);
    return box;
  }

  it("lands at the caret saved when Dictate was pressed, and leaves the caret after it", async () => {
    const box = await dictateInto("Summarise the board pack and ", null, "focus on churn");

    expect(messageOf(box)).toBe("Summarise the board pack and focus on churn");
    await waitFor(() => expect(box).toHaveFocus());
    await waitFor(() => expect(caretOf(box)).toBe(messageOf(box).length));
  });

  it("replaces a selection", async () => {
    const box = await dictateInto("Summarise the board pack", [0, 9], "Shorten");

    expect(messageOf(box)).toBe("Shorten the board pack");
    await waitFor(() => expect(caretOf(box)).toBe(7));
  });

  it("adds a joining space after a word", async () => {
    const box = await dictateInto("Summarise", null, "the board pack");

    expect(messageOf(box)).toBe("Summarise the board pack");
  });

  it("adds a space after the transcript when a word follows the caret, and leaves the caret past it", async () => {
    const box = await dictateInto("Summarise pack", [10, 10], "the board");

    expect(messageOf(box)).toBe("Summarise the board pack");
    await waitFor(() => expect(caretOf(box)).toBe("Summarise the board ".length));
  });

  it("fills an empty box without a leading space", async () => {
    const box = await dictateInto("", null, "hello there");

    expect(messageOf(box)).toBe("hello there");
  });

  it("says how many words landed", async () => {
    await dictateInto("", null, "focus on   churn");

    expect(document.querySelector('[role="status"][aria-live="polite"]')).toHaveTextContent(
      "Inserted 3 words",
    );
  });

  it("counts words the way the strip does, which spaces alone would not", async () => {
    await dictateInto("", null, "我们明天开会");

    expect(document.querySelector('[role="status"][aria-live="polite"]')).toHaveTextContent(
      "Inserted 3 words",
    );
  });

  it("puts the note away on the next key, but not on a modifier alone", async () => {
    const dictation = serverDictation({}, { inserted: true, transcript: { id: 1, text: "hi" } });
    render(<ChatInput onSend={vi.fn()} dictation={dictation} />);
    const box = screen.getByRole("textbox");

    fireEvent.keyDown(box, { key: "Shift" });
    expect(dictation.actions.dismissInserted).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "a" });

    expect(dictation.actions.dismissInserted).toHaveBeenCalledOnce();
  });

  it("has nothing to put away when nothing was just inserted", () => {
    const dictation = serverDictation();
    render(<ChatInput onSend={vi.fn()} dictation={dictation} />);

    fireEvent.keyDown(screen.getByRole("textbox"), { key: "a" });

    expect(dictation.actions.dismissInserted).not.toHaveBeenCalled();
  });

  it("goes at the end, joined by a space, when the text was edited while a failure waited", async () => {
    const dictation = serverDictation();
    const { rerender } = render(<ChatInput onSend={vi.fn()} dictation={dictation} />);
    const box = screen.getByRole("textbox");
    const step = (state: Partial<DictationState>) =>
      rerender(<ChatInput onSend={vi.fn()} dictation={moved(dictation, state)} />);
    await pressDictate();
    step({ phase: "transcribing" });
    step({ phase: "failed", reason: "provider_error", canRetry: true });

    await userEvent.type(box, "Hello");
    // Retry, from the strip under the box: Dictate was not pressed again.
    step({ phase: "transcribing" });
    step({ phase: "idle", transcript: { id: 1, text: "focus on churn" } });

    expect(messageOf(box)).toBe("Hello focus on churn");
    await waitFor(() => expect(caretOf(box)).toBe(messageOf(box).length));
  });

  it("inserts nothing for a transcript nobody pressed Dictate for", () => {
    const dictation = serverDictation();
    const { rerender } = render(<ChatInput onSend={vi.fn()} dictation={dictation} />);

    rerender(
      <ChatInput
        onSend={vi.fn()}
        dictation={moved(dictation, { transcript: { id: 4, text: "stray" } })}
      />,
    );

    expect(messageOf(screen.getByRole("textbox"))).toBe("");
  });
});

describe("a run waiting for its person", () => {
  it("disables Stop while cancelling without showing Call", async () => {
    const stop = vi.fn();
    render(
      <ChatInput
        onSend={vi.fn()}
        canStop
        stopDisabled
        onStop={stop}
        idleSlot={<button>Call</button>}
      />,
    );
    const button = screen.getByRole("button", { name: "Stop generating" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(stop).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Call" })).not.toBeInTheDocument();
  });

  it("offers Stop instead of Call even though the parked turn is not streaming", async () => {
    const stop = vi.fn();
    render(
      <ChatInput
        onSend={vi.fn()}
        disabled
        isProcessing={false}
        canStop
        onStop={stop}
        idleSlot={<button>Call</button>}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    expect(stop).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Call" })).not.toBeInTheDocument();
  });
});
