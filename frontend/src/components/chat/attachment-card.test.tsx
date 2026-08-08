import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AttachmentCard, PendingAttachmentCard } from "./attachment-card";
import type { FileUploadResponse } from "@/lib/file-api";

// next/image wants a configured loader and a layout it cannot get in jsdom; the
// card only cares that the thumbnail points at the file.
vi.mock("next/image", () => ({
  // eslint-disable-next-line @next/next/no-img-element
  default: (props: { src: string; alt: string }) => <img src={props.src} alt={props.alt} />,
}));

function file(overrides: Partial<FileUploadResponse> = {}): FileUploadResponse {
  return {
    id: "f-1",
    filename: "quarterly-report.txt",
    mime_type: "text/plain",
    size: 48 * 1024,
    file_type: "text",
    preview: "date,region,revenue\n2026-01,EU,120\n2026-01,US,340",
    ...overrides,
  };
}

describe("AttachmentCard", () => {
  it("names the file in full, so the wrong one is visible before it is sent", () => {
    // The pill this replaced truncated at 150px, which turns two builds of the
    // same export into the same string.
    render(
      <AttachmentCard
        file={file({ filename: "allegro_system_prompt_v2_final.txt" })}
        onRemove={vi.fn()}
      />,
    );

    expect(screen.getByText("allegro_system_prompt_v2_final.txt")).toBeVisible();
  });

  it("shows what is in the file, which is the part a filename cannot carry", () => {
    render(<AttachmentCard file={file()} onRemove={vi.fn()} />);

    expect(screen.getByText(/2026-01,EU,120/)).toBeVisible();
  });

  it("says what it is and how big, from the extension rather than the MIME type", () => {
    render(<AttachmentCard file={file()} onRemove={vi.fn()} />);

    expect(screen.getByText("TXT · 48.0 KB")).toBeVisible();
  });

  it("falls back to the classified type when the name has no extension", () => {
    render(<AttachmentCard file={file({ filename: "Dockerfile" })} onRemove={vi.fn()} />);

    expect(screen.getByText("TEXT · 48.0 KB")).toBeVisible();
  });

  it("labels a paste as one, not by the filename nobody chose", () => {
    render(
      <AttachmentCard
        file={file({ filename: "pasted-2026-08-08.txt" })}
        pasted
        onRemove={vi.fn()}
      />,
    );

    expect(screen.getByText("Pasted · 48.0 KB")).toBeVisible();
  });

  it("shows an image as a thumbnail where the excerpt would be", () => {
    render(
      <AttachmentCard
        file={file({ filename: "screenshot.png", mime_type: "image/png", file_type: "image" })}
        onRemove={vi.fn()}
      />,
    );

    expect(screen.getByRole("img", { name: "screenshot.png" })).toHaveAttribute(
      "src",
      "/api/files/f-1",
    );
  });

  it("quotes nothing when there is nothing to quote", () => {
    // An image has no parsed text, and neither does a file the parser refused.
    // An empty quote block reads as an empty file.
    const { container } = render(
      <AttachmentCard file={file({ preview: null })} onRemove={vi.fn()} />,
    );

    expect(container.querySelector(".font-mono.whitespace-pre-wrap")).toBeNull();
  });

  it("offers remove without a hover, which a touch screen cannot supply", async () => {
    const onRemove = vi.fn();
    render(<AttachmentCard file={file()} onRemove={onRemove} />);

    const remove = screen.getByRole("button", { name: "Remove quarterly-report.txt" });
    expect(remove).toBeVisible();

    await userEvent.click(remove);

    expect(onRemove).toHaveBeenCalledOnce();
  });
});

describe("PendingAttachmentCard", () => {
  it("holds the place the finished card will take", () => {
    render(<PendingAttachmentCard name="notes.md" size={2048} />);

    expect(screen.getByText("notes.md")).toBeVisible();
    expect(screen.getByText("Uploading · 2.0 KB")).toBeVisible();
  });
});
