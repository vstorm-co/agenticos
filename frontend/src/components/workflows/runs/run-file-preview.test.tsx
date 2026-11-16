import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { saveBlob } from "@/lib/file-access";
import {
  readWorkflowMediaPreview,
  WORKFLOW_MEDIA_PREVIEW_BYTES,
} from "@/lib/workflows/media-preview";
import type { WorkflowRunFile } from "@/lib/workflows/types";
import { useAuthStore, useOrgStore } from "@/stores";

import { RunFilePreview } from "./run-file-preview";

vi.mock("@/lib/workflows/media-preview", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/workflows/media-preview")>()),
  readWorkflowMediaPreview: vi.fn(),
}));
vi.mock("@/lib/file-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/file-access")>()),
  saveBlob: vi.fn(),
}));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <div>{content}</div>,
}));

const USER = {
  id: "account-a",
  email: "a@example.invalid",
  is_active: true,
  created_at: "2026-11-16T00:00:00Z",
};
const FILE: WorkflowRunFile = {
  id: "file-a",
  filename: "image.png",
  content_type: "image/png",
  byte_size: 4,
  producing_node_run_id: "node-a",
  created_at: "2026-11-16T00:00:00Z",
};
const clients: QueryClient[] = [];
const created: string[] = [];
const revoked: string[] = [];

function mount(file = FILE) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { ...render(<RunFilePreview runId="run-a" file={file} />, { wrapper }), client };
}

async function open(name = "image.png") {
  await userEvent.click(screen.getByRole("button", { name: `Preview ${name}` }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
}

function pendingRead() {
  let resolve!: (blob: Blob) => void;
  const promise = new Promise<Blob>((done) => {
    resolve = done;
  });
  vi.mocked(readWorkflowMediaPreview).mockReturnValue(promise);
  return { resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  created.length = 0;
  revoked.length = 0;
  useAuthStore.setState({
    user: USER,
    sessionOwnerId: USER.id,
    isAuthenticated: true,
    impersonationRevoked: false,
  });
  useOrgStore.setState({ activeOrgId: "org-a", refusedOrgIds: [] });
  Object.assign(URL, {
    createObjectURL: () => {
      const url = `blob:preview-${created.length}`;
      created.push(url);
      return url;
    },
    revokeObjectURL: (url: string) => revoked.push(url),
  });
  vi.mocked(readWorkflowMediaPreview).mockResolvedValue(new Blob(["data"], { type: "image/png" }));
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
});

describe("workflow run file preview", () => {
  it("waits for an explicit click, uses the shared viewer and discards the bytes on close", async () => {
    const { client } = mount();
    expect(readWorkflowMediaPreview).not.toHaveBeenCalled();
    await open();
    const picture = await screen.findByRole("img", { name: "image.png" });
    expect(picture).toHaveAttribute("src", "blob:preview-0");
    expect(readWorkflowMediaPreview).toHaveBeenCalledWith("run-a", FILE, expect.any(AbortSignal));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(revoked).toEqual(["blob:preview-0"]);
    await waitFor(() => expect(client.getQueryCache().getAll()).toHaveLength(0));
    await open();
    await screen.findByRole("img", { name: "image.png" });
    expect(readWorkflowMediaPreview).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["audio/mpeg", "sound.mp3", "audio"],
    ["video/mp4", "clip.mp4", "video"],
  ])("uses the shared %s player for authenticated bytes", async (content_type, filename, tag) => {
    vi.mocked(readWorkflowMediaPreview).mockResolvedValue(
      new Blob(["data"], { type: content_type }),
    );
    mount({ ...FILE, content_type, filename });
    await open(filename);
    await waitFor(() =>
      expect(document.querySelector(tag)).toHaveAttribute("src", "blob:preview-0"),
    );
    expect(document.querySelector(tag)).toHaveAttribute("controls");
  });

  it("saves through the same bounded authorized read and keeps a missing filename usable", async () => {
    mount({ ...FILE, filename: null });
    await open(FILE.id);
    await screen.findByRole("img", { name: FILE.id });
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(expect.any(Blob), FILE.id));
    expect(readWorkflowMediaPreview).toHaveBeenCalledTimes(2);
  });

  it.each([
    { ...FILE, content_type: "text/html" },
    { ...FILE, content_type: "image/svg+xml" },
    { ...FILE, byte_size: WORKFLOW_MEDIA_PREVIEW_BYTES + 1 },
  ])("offers no inline action for unsupported or excessive content %j", (file) => {
    mount(file);
    expect(screen.queryByRole("button")).toBeNull();
    expect(readWorkflowMediaPreview).not.toHaveBeenCalled();
  });

  it("never turns an SVG filename into a text or markup fetch", async () => {
    mount({ ...FILE, filename: "picture.svg" });
    await open("picture.svg");
    expect(await screen.findByText("That file could not be read")).toBeInTheDocument();
    expect(readWorkflowMediaPreview).not.toHaveBeenCalled();
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("cancels a pending read and cannot paint its late bytes after close", async () => {
    const pending = pendingRead();
    const { client } = mount();
    await open();
    const signal = vi.mocked(readWorkflowMediaPreview).mock.calls[0]?.[2];
    await userEvent.keyboard("{Escape}");
    expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve(new Blob(["late"], { type: "image/png" })));
    expect(created).toEqual([]);
    await waitFor(() => expect(client.getQueryCache().getAll()).toHaveLength(0));
  });

  it.each([
    ["organization", () => useOrgStore.setState({ activeOrgId: "org-b" })],
    [
      "account",
      () =>
        useAuthStore.setState({ user: { ...USER, id: "account-b" }, sessionOwnerId: "account-b" }),
    ],
    ["session owner", () => useAuthStore.setState({ sessionOwnerId: "account-b" })],
    ["sign-out", () => useAuthStore.setState({ isAuthenticated: false, user: null })],
    ["organization refusal", () => useOrgStore.setState({ refusedOrgIds: ["org-a"] })],
    ["impersonation expiry", () => useAuthStore.setState({ impersonationRevoked: true })],
  ] as const)("closes and discards a pending read when %s changes", async (_label, change) => {
    const pending = pendingRead();
    mount();
    await open();
    const signal = vi.mocked(readWorkflowMediaPreview).mock.calls[0]?.[2];
    act(change);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve(new Blob(["late"], { type: "image/png" })));
    expect(created).toEqual([]);
  });

  it.each([
    ["no authenticated session", () => useAuthStore.setState({ isAuthenticated: false })],
    ["no user", () => useAuthStore.setState({ user: null })],
    ["no organization", () => useOrgStore.setState({ activeOrgId: null })],
    ["refused organization", () => useOrgStore.setState({ refusedOrgIds: ["org-a"] })],
    ["expired impersonation", () => useAuthStore.setState({ impersonationRevoked: true })],
  ] as const)("refuses a read with %s", async (_label, change) => {
    change();
    mount();
    await open();
    expect(await screen.findByText("That file could not be read")).toBeInTheDocument();
    expect(readWorkflowMediaPreview).not.toHaveBeenCalled();
  });

  it.each([
    { runId: "run-b", file: FILE },
    { runId: "run-a", file: { ...FILE, id: "file-b" } },
    { runId: "run-a", file: { ...FILE, byte_size: 8 } },
    { runId: "run-a", file: { ...FILE, content_type: "video/mp4" } },
  ])("closes when the addressed resource changes %j", async (props) => {
    const { rerender } = mount();
    await open();
    await screen.findByRole("img", { name: "image.png" });
    rerender(<RunFilePreview {...props} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(revoked).toEqual(created);
  });

  it("does not reuse a previous scope's cached picture after switching away and back", async () => {
    mount();
    await open();
    await screen.findByRole("img", { name: "image.png" });
    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    act(() => useOrgStore.setState({ activeOrgId: "org-a" }));
    pendingRead();
    await open();
    expect(screen.queryByRole("img", { name: "image.png" })).toBeNull();
    expect(readWorkflowMediaPreview).toHaveBeenCalledTimes(2);
  });

  it("rejects an old download even if the user returns to the original organization", async () => {
    mount();
    await open();
    await screen.findByRole("img", { name: "image.png" });
    const pending = pendingRead();
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    act(() => useOrgStore.setState({ activeOrgId: "org-a" }));
    await act(async () => pending.resolve(new Blob(["late"], { type: "image/png" })));
    expect(saveBlob).not.toHaveBeenCalled();
  });

  it("shows a failed authorized read without retrying it", async () => {
    vi.mocked(readWorkflowMediaPreview).mockRejectedValue(new Error("not available"));
    mount();
    await open();
    expect(await screen.findByText("not available")).toBeInTheDocument();
    expect(readWorkflowMediaPreview).toHaveBeenCalledTimes(1);
  });
});
