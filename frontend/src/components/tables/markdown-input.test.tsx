import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { MarkdownInput } from "./markdown-input";
import { uploadTableImage, discardTableImage } from "@/lib/tables-api";
vi.mock("@/lib/tables-api", () => ({ uploadTableImage: vi.fn(), discardTableImage: vi.fn() }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(discardTableImage).mockResolvedValue(undefined);
});
const image = () => new File(["png"], "image.png", { type: "image/png" });
function Editor() {
  const [value, setValue] = useState("");
  return (
    <MarkdownInput
      id="body"
      aria-label="Body"
      value={value}
      onValueChange={setValue}
      onImageInserted={vi.fn()}
      tableId="table"
    />
  );
}
it("inserts a block by pointer and closes its menu when scrolling", async () => {
  render(<Editor />);
  const input = screen.getByRole("textbox", { name: "Body" });
  await userEvent.type(input, "/");
  await userEvent.click(screen.getByRole("button", { name: "To-do list" }));
  expect(input).toHaveValue("- [ ] ");
  await userEvent.clear(input);
  await userEvent.type(input, "/");
  fireEvent.scroll(input);
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});
it("returns the caret after a successfully pasted image", async () => {
  vi.mocked(uploadTableImage).mockResolvedValueOnce({ id: "one", url: "/image" });
  render(<Editor />);
  const input = screen.getByRole("textbox", { name: "Body" });
  await userEvent.click(input);
  fireEvent.paste(input, { clipboardData: { files: [image()] } });
  await waitFor(() => expect(input).toHaveValue("![](/image)"));
  if (!(input instanceof HTMLTextAreaElement)) throw new Error("Expected a textarea");
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  expect(input.selectionStart).toBe(11);
});
it("leaves plain clipboard text and read-only fields to the native input", () => {
  const props = {
    id: "body",
    "aria-label": "Body",
    value: "Keep",
    onValueChange: vi.fn(),
    onImageInserted: vi.fn(),
  };
  const { rerender } = render(<MarkdownInput {...props} tableId="table" />);
  expect(fireEvent.paste(screen.getByRole("textbox"), { clipboardData: { files: [] } })).toBe(true);
  rerender(<MarkdownInput {...props} tableId="table" readOnly />);
  expect(
    fireEvent.paste(screen.getByRole("textbox"), { clipboardData: { files: [image()] } }),
  ).toBe(true);
  expect(uploadTableImage).not.toHaveBeenCalled();
});
it("rejects missing table context and images larger than 5 MiB before upload", async () => {
  const props = {
    id: "body",
    "aria-label": "Body",
    value: "Keep",
    onValueChange: vi.fn(),
    onImageInserted: vi.fn(),
  };
  const { rerender } = render(<MarkdownInput {...props} />);
  fireEvent.paste(screen.getByRole("textbox"), { clipboardData: { files: [image()] } });
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not paste the image");
  rerender(<MarkdownInput {...props} tableId="table" />);
  fireEvent.paste(screen.getByRole("textbox"), {
    clipboardData: {
      files: [new File([new Uint8Array(5 * 1024 * 1024 + 1)], "large.png", { type: "image/png" })],
    },
  });
  expect(uploadTableImage).not.toHaveBeenCalled();
});
it("discards a completed upload after a concurrent document change", async () => {
  let finish: ((value: { id: string; url: string }) => void) | undefined;
  vi.mocked(uploadTableImage).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const props = {
    id: "body",
    "aria-label": "Body",
    onValueChange: vi.fn(),
    onImageInserted: vi.fn(),
    tableId: "table",
  };
  const { rerender } = render(<MarkdownInput {...props} value="Original" />);
  fireEvent.paste(screen.getByRole("textbox"), { clipboardData: { files: [image()] } });
  rerender(<MarkdownInput {...props} value="Changed elsewhere" />);
  finish?.({ id: "stale", url: "/stale" });
  await waitFor(() => expect(discardTableImage).toHaveBeenCalledWith("table", "stale"));
  expect(props.onValueChange).not.toHaveBeenCalled();
});
it("surfaces failed cleanup rather than claiming the paste succeeded", async () => {
  vi.mocked(uploadTableImage)
    .mockResolvedValueOnce({ id: "first", url: "/first" })
    .mockRejectedValueOnce(new Error("Quota"));
  vi.mocked(discardTableImage).mockRejectedValueOnce(new Error("Disconnected"));
  render(<Editor />);
  fireEvent.paste(screen.getByRole("textbox"), { clipboardData: { files: [image(), image()] } });
  await waitFor(() => expect(discardTableImage).toHaveBeenCalledWith("table", "first"));
  expect(screen.getByRole("alert")).toHaveTextContent("Could not paste the image");
  expect(screen.getByRole("textbox")).toHaveValue("");
});
