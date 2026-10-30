import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { UploadProgressList } from "./upload-progress-list";
const uploads = Array.from({ length: 5 }, (_, i) => ({
  uploadId: `${i}`,
  filename: `file-${i}.md`,
  percent: i * 10,
}));
describe("Upload queue", () => {
  it("keeps a compact queue while reporting how many files remain", () => {
    render(<UploadProgressList uploads={uploads} limit={3} />);
    expect(screen.getAllByRole("progressbar")).toHaveLength(3);
    expect(screen.getByRole("status")).toHaveTextContent("2 more files in the upload queue");
    expect(screen.getByRole("progressbar", { name: "file-1.md" })).toHaveAttribute(
      "aria-valuenow",
      "10",
    );
    expect(screen.queryByText("file-4.md")).not.toBeInTheDocument();
  });
  it("shows the complete queue when no limit is requested", () => {
    render(<UploadProgressList uploads={uploads} />);
    expect(screen.getAllByRole("progressbar")).toHaveLength(5);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
