import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FileBytesView, FileTextView, FileUnavailable } from "./file-render";

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

/**
 * A file made of characters, as whatever those characters are.
 *
 * Six kinds where the chat panel had a viewer per kind and the workspace dialog had
 * two branches - Markdown or a `<pre>` - so a CSV an agent wrote rendered as a wall
 * of commas and an HTML page as its own tags.
 */
describe("showing a file's characters", () => {
  it("renders Markdown as Markdown", () => {
    render(<FileTextView kind="markdown" name="notes.md" text="# Title" />);

    expect(screen.getByTestId("markdown")).toHaveTextContent("# Title");
  });

  it("renders an HTML page, sandboxed so nothing in it can run", () => {
    // The API refuses to serve HTML inline for exactly this reason: a document an
    // agent wrote, served from this origin, is stored XSS. From `srcDoc` into an
    // opaque origin it reaches no script, no cookie and no DOM.
    render(<FileTextView kind="html" name="report.html" text="<p>hello</p>" />);

    const frame = screen.getByTitle("report.html, rendered");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame).toHaveAttribute("srcdoc", "<p>hello</p>");
  });

  it("renders a delimited file as a table", () => {
    render(<FileTextView kind="csv" name="report.csv" text={"name,total\nAcme,42"} />);

    expect(screen.getByRole("columnheader", { name: "name" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Acme" })).toBeInTheDocument();
  });

  it("indents JSON, and shows it as it stands when it does not parse", () => {
    const { unmount } = render(<FileTextView kind="json" name="a.json" text='{"a":1}' />);
    expect(screen.getByText(/"a": 1/)).toBeInTheDocument();
    unmount();

    render(<FileTextView kind="json" name="a.json" text="{not json" />);
    expect(screen.getByText("{not json")).toBeInTheDocument();
  });

  it("fences code with the language its name implies", () => {
    // Reusing the Markdown pipeline is what gives syntax highlighting for free.
    render(<FileTextView kind="code" name="run.py" text="print(1)" />);

    expect(screen.getByTestId("markdown")).toHaveTextContent("```python");
  });

  it("fences a file whose language nobody mapped as plain text", () => {
    render(<FileTextView kind="code" name="thing.unknownlang" text="something" />);

    expect(screen.getByTestId("markdown")).toHaveTextContent("```text");
  });

  it("shows plain text as it is, preserving its whitespace", () => {
    render(<FileTextView kind="text" name="a.log" text={"line one\n  line two"} />);

    // `pre`, not `pre-wrap`: source is read by its indentation, and wrapping a long
    // line back to the left margin destroys the thing a Source view is for.
    expect(screen.getByText(/line one/)).toHaveClass("whitespace-pre");
  });

  it("shows the characters when that is what was asked for", () => {
    // Both are the file. A `#` that silently became large type is how somebody fails
    // to notice their agent is writing Markdown into a file nothing reads as Markdown.
    render(<FileTextView kind="markdown" name="notes.md" text="# Title" asSource />);

    expect(screen.queryByTestId("markdown")).toBeNull();
    expect(screen.getByText("# Title")).toBeInTheDocument();
  });

  it("says a file is empty rather than rendering nothing at all", () => {
    render(<FileTextView kind="markdown" name="notes.md" text={"   \n "} />);

    expect(screen.getByText("This file is empty.")).toBeInTheDocument();
  });

  it("shows a kind with no rendered form as its characters", () => {
    // A skill's file is text already in hand, and its name can be anything.
    render(<FileTextView kind="image" name="logo.png" text="not really a png" />);

    expect(screen.getByText("not really a png")).toBeInTheDocument();
  });
});

describe("the table a delimited file becomes", () => {
  it("says an empty file is empty rather than showing an empty table", () => {
    render(<FileTextView kind="csv" name="a.csv" text=" " />);

    expect(screen.getByText("This file is empty.")).toBeInTheDocument();
  });

  it("shows the first five hundred rows and says how many there are", () => {
    // A hundred thousand rows in the DOM is a dialog that never opens, and a table
    // silently missing its tail is a table that lies about the file.
    const rows = ["name", ...Array.from({ length: 600 }, (_, index) => `row-${index}`)].join("\n");
    render(<FileTextView kind="csv" name="a.csv" text={rows} />);

    expect(screen.getByText(/Showing 500 of 600 rows/)).toBeInTheDocument();
    // 500 body rows plus the header.
    expect(screen.getAllByRole("row")).toHaveLength(501);
  });

  it("says nothing about truncation for a file that fits", () => {
    render(<FileTextView kind="csv" name="a.csv" text={"name\nAcme"} />);

    expect(screen.queryByText(/Showing/)).toBeNull();
  });

  it("renders a header row a file has and no body it does not", () => {
    render(<FileTextView kind="csv" name="a.csv" text="name,total" />);

    expect(screen.getAllByRole("row")).toHaveLength(1);
  });
});

/**
 * A file made of bytes, as whatever the *server* agreed to call it.
 *
 * The branch is on the media type and never on the name, because what may be
 * displayed is the API's decision: a short allowlist of raster images plus PDF, and
 * everything else typed `application/octet-stream` precisely so a browser cannot
 * decide a body is HTML after all.
 */
describe("showing a file's bytes", () => {
  const props = { name: "chart.png", url: "blob:x", onDownload: () => {} };

  it("shows an image with the filename as its alternative text", () => {
    render(<FileBytesView {...props} mediaType="image/png" />);

    expect(screen.getByRole("img", { name: "chart.png" })).toHaveAttribute("src", "blob:x");
  });

  it("renders a PDF in a frame the browser routes to its own viewer", () => {
    render(<FileBytesView {...props} name="report.pdf" mediaType="application/pdf" />);

    expect(screen.getByTitle("report.pdf")).toHaveAttribute("src", "blob:x");
  });

  it("plays video and audio with controls", () => {
    const video = render(<FileBytesView {...props} name="demo.mp4" mediaType="video/mp4" />);
    expect(video.container.querySelector("video")).toHaveAttribute("controls");
    video.unmount();

    const audio = render(<FileBytesView {...props} name="call.mp3" mediaType="audio/mpeg" />);
    expect(audio.container.querySelector("audio")).toHaveAttribute("controls");
  });

  it("offers a download when the server did not serve it as anything showable", async () => {
    // Whatever the name suggested. A broken `<img>` with nothing saying why is the
    // worst of the three answers; the download is the one that works.
    const onDownload = vi.fn();
    render(
      <FileBytesView
        name="logo.svg"
        url="blob:x"
        mediaType="application/octet-stream"
        onDownload={onDownload}
      />,
    );

    expect(
      screen.getByText("This one cannot be shown here — the server serves it as a file."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Download/ }));
    expect(onDownload).toHaveBeenCalled();
  });
});

describe("a file that cannot be shown", () => {
  it("says why, and offers the way to read it anyway", () => {
    render(<FileUnavailable reason="404 Not Found" onDownload={() => {}} />);

    expect(screen.getByText("404 Not Found")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download/ })).toBeInTheDocument();
  });

  it("says when the offer itself failed", () => {
    // A container-backed host refuses a binary either way, so the download can fail
    // too - and silently, before this.
    render(
      <FileUnavailable
        reason="404 Not Found"
        onDownload={() => {}}
        error="This host can only read text"
      />,
    );

    expect(screen.getByText("This host can only read text")).toBeInTheDocument();
  });
});

describe("the Source view", () => {
  const CSV = ["run_id,cost", "a-1,0.04", "a-2,0.09"].join("\n");

  it("numbers the lines, and keeps the numbers out of the text", () => {
    // A bare `pre` of 4,000 columns of CSV says nothing about which line anything
    // is on - and a reader dragging across the block must not pick up the gutter,
    // or every paste needs cleaning by hand.
    render(<FileTextView kind="csv" name="runs.csv" text={CSV} asSource />);

    // Testing Library normalises whitespace, so the gutter is found by what it is
    // rather than by its text.
    const gutter = document.querySelector("pre[aria-hidden]")!;

    expect(gutter.textContent).toBe("1\n2\n3");

    expect(gutter).toHaveClass("select-none");
  });

  it("offers the whole file to the clipboard", () => {
    render(<FileTextView kind="csv" name="runs.csv" text={CSV} asSource />);

    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("draws no gutter for a file with more lines than one is worth", () => {
    // One element per line, and a numbered gutter on fifty thousand of them costs
    // more than it tells anybody.
    const huge = Array.from({ length: 5001 }, (_, n) => `row-${n}`).join("\n");

    render(<FileTextView kind="csv" name="runs.csv" text={huge} asSource />);

    expect(document.querySelector("pre[aria-hidden]")).toBeNull();
  });
});
