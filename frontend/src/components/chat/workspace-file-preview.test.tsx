import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WorkspaceFilePreview } from "./workspace-file-preview";
import type { FileAccess } from "@/lib/file-access";

vi.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));

function access(): FileAccess {
  return {
    textKey: ["file", "text"],
    bytesKey: ["file", "bytes"],
    readText: async () => ({ content: "# Preview source", truncated: false }),
    readBytes: async () => new Blob(["example"]),
    download: vi.fn().mockRejectedValue(new Error("Download failed")),
  };
}

it("switches source views and reports download failures without dismissing the reader", async () => {
  const back = vi.fn();
  const origin = access();
  const view = render(
    <QueryClientProvider client={new QueryClient()}>
      <WorkspaceFilePreview
        file={{ name: "notes.md", path: "out/notes.md" }}
        access={origin}
        onBack={back}
      />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("# Preview source")).toBeVisible();
  fireEvent.keyDown(screen.getByRole("heading"), { key: "ArrowRight" });
  await userEvent.click(screen.getByRole("button", { name: "Source" }));
  expect(
    await screen.findByText(
      (_, element) => element?.tagName === "PRE" && element.textContent === "# Preview source",
    ),
  ).toHaveTextContent("# Preview source");
  await userEvent.click(screen.getByRole("button", { name: "Download" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Download failed");
  await userEvent.click(screen.getByRole("button", { name: "Back to all files" }));
  expect(back).toHaveBeenCalledOnce();
  view.unmount();
});

it("pages attachments by keyboard and buttons while leaving text editing keys alone", async () => {
  const select = vi.fn();
  const client = new QueryClient();
  const origin = access();
  function Reader({ index = 1 }: { index?: number }) {
    return (
      <QueryClientProvider client={client}>
        <WorkspaceFilePreview
          file={{ name: "notes.md", size: 3 }}
          access={origin}
          onBack={vi.fn()}
          navigation={{ names: ["first.md", "notes.md", "last.md"], index, onSelect: select }}
        />
      </QueryClientProvider>
    );
  }
  const view = render(<Reader />);
  const heading = screen.getByRole("heading");
  fireEvent.keyDown(heading, { key: "ArrowLeft" });
  expect(select).toHaveBeenLastCalledWith(0);
  fireEvent.keyDown(heading, { key: "ArrowRight" });
  expect(select).toHaveBeenLastCalledWith(2);
  fireEvent.keyDown(heading, { key: "x" });
  expect(select).toHaveBeenCalledTimes(2);
  await userEvent.click(screen.getByRole("button", { name: "Source" }));
  const text = await screen.findByText(
    (_, element) => element?.tagName === "PRE" && element.textContent === "# Preview source",
  );
  const input = document.createElement("input");
  text.append(input);
  fireEvent.keyDown(input, { key: "ArrowRight" });
  input.remove();
  expect(select).toHaveBeenCalledTimes(2);
  await userEvent.click(screen.getByRole("button", { name: "Next file" }));
  expect(select).toHaveBeenLastCalledWith(2);
  view.rerender(<Reader index={0} />);
  fireEvent.keyDown(screen.getByRole("heading"), { key: "ArrowLeft" });
  expect(select).toHaveBeenCalledTimes(3);
  view.rerender(<Reader index={2} />);
  fireEvent.keyDown(screen.getByRole("heading"), { key: "ArrowRight" });
  expect(select).toHaveBeenCalledTimes(3);
});
