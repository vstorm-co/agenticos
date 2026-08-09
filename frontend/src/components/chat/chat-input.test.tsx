import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatInput } from "./chat-input";
import type { FileUploadResponse } from "@/lib/file-api";

const state = vi.hoisted(() => ({
  upload: vi.fn<(file: File) => Promise<FileUploadResponse>>(),
}));

vi.mock("@/lib/file-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/file-api")>()),
  uploadFile: (file: File) => state.upload(file),
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn() } }));

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

beforeEach(() => {
  state.upload.mockReset();
  state.upload.mockResolvedValue(uploaded());
});

describe("ChatInput paste", () => {
  it("turns a long paste into an attachment and leaves the composer empty", async () => {
    // The point of the whole feature: the question somebody is about to type has
    // to still fit on the screen after they paste the thing it is about.
    render(<ChatInput onSend={vi.fn()} />);
    const textarea = screen.getByRole("textbox");

    await userEvent.click(textarea);
    await userEvent.paste(LONG);

    expect(await screen.findByText("pasted-2026-08-08.txt")).toBeVisible();
    expect(screen.getByText("Pasted · 48.8 KB")).toBeVisible();
    expect(textarea).toHaveValue("");
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

  it("leaves a short paste alone - somebody who pastes a paragraph meant to send it", async () => {
    render(<ChatInput onSend={vi.fn()} />);
    const textarea = screen.getByRole("textbox");

    await userEvent.click(textarea);
    await userEvent.paste("what does this error mean?");

    expect(textarea).toHaveValue("what does this error mean?");
    expect(state.upload).not.toHaveBeenCalled();
  });

  it("sends the attachment with the question typed beside it", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByRole("textbox");

    await userEvent.click(textarea);
    await userEvent.paste(LONG);
    await screen.findByText("pasted-2026-08-08.txt");
    await userEvent.type(textarea, "why does this fail?");
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(onSend).toHaveBeenCalledWith("why does this fail?", ["f-1"], [uploaded()]);
  });
});

describe("ChatInput attachments", () => {
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
});
