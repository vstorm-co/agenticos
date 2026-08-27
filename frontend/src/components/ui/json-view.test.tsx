import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { JsonView } from "./json-view";

/**
 * JSON somebody has to read.
 *
 * The payload this was written for is a document's stored chunks: four records
 * whose interesting field is a 500-character string with escaped newlines in it.
 * Pretty-printed in a `<pre>` that is a horizontal scrollbar, so what is asserted
 * here is the three things that fix it - the shape folds, long values clamp, and a
 * newline inside a string is a newline.
 */

const RECORDS = {
  chunk_count: 2,
  has_text: true,
  parser: null,
  chunks: [
    { page_num: 1, content: "the first chunk" },
    { page_num: 2, content: "the second chunk" },
  ],
};

describe("reading a JSON payload", () => {
  it("opens to the depth it was given and folds what is deeper", () => {
    render(<JsonView value={RECORDS} initialDepth={2} />);

    // The array is open at depth 1; the records inside it are not.
    expect(screen.getByText("chunks:")).toBeInTheDocument();
    expect(screen.getAllByText("{ 2 keys }")).toHaveLength(2);
    expect(screen.queryByText("the first chunk")).toBeNull();
  });

  it("opens a folded node when it is asked to", async () => {
    render(<JsonView value={RECORDS} initialDepth={2} />);
    await userEvent.click(screen.getAllByText("{ 2 keys }")[0]!);

    expect(screen.getByText("the first chunk")).toBeInTheDocument();
  });

  it("folds a node that was open, and says what is inside it", async () => {
    render(<JsonView value={RECORDS} initialDepth={3} />);
    await userEvent.click(screen.getByRole("button", { name: /chunks:/ }));

    expect(screen.queryByText("the first chunk")).toBeNull();
    expect(screen.getByText("[ 2 items ]")).toBeInTheDocument();
  });

  it("says an empty container is empty rather than drawing nothing", () => {
    render(<JsonView value={{ nothing: [], neither: {} }} initialDepth={1} />);

    expect(screen.getByText("[ empty ]")).toBeInTheDocument();
    expect(screen.getByText("{ empty }")).toBeInTheDocument();
  });

  it("draws null and the two kinds of scalar as themselves", () => {
    render(<JsonView value={RECORDS} initialDepth={1} />);

    expect(screen.getByText("null")).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("clamps a long string and offers the rest, with its length", async () => {
    // A parsed chunk is half a page of text, and a record whose value is half a
    // page is a record you cannot see the next one from.
    const long = "x".repeat(500);
    render(<JsonView value={{ content: long }} />);

    const shown = screen.getByText(long);
    expect(shown).toHaveClass("line-clamp-4");

    await userEvent.click(screen.getByRole("button", { name: "show all 500 characters" }));
    expect(screen.getByText(long)).not.toHaveClass("line-clamp-4");
    await userEvent.click(screen.getByRole("button", { name: "show less" }));
    expect(screen.getByText(long)).toHaveClass("line-clamp-4");
  });

  it("clamps on the line count too, not only on the length", () => {
    // Five short lines is not a long string by any character count, and it is
    // still five lines of one record.
    render(<JsonView value={{ content: "a\nb\nc\nd\ne" }} />);

    expect(screen.getByRole("button", { name: /show all/ })).toBeInTheDocument();
  });

  it("leaves a short string alone", () => {
    render(<JsonView value={{ content: "short" }} />);

    expect(screen.getByText("short")).not.toHaveClass("line-clamp-4");
    expect(screen.queryByRole("button", { name: /show all/ })).toBeNull();
  });

  it("draws a newline inside a string as a newline, because that is what it is", () => {
    render(<JsonView value={{ content: "first\nsecond" }} />);

    expect(screen.getByText(/first/)).toHaveClass("whitespace-pre-wrap");
  });

  it("renders a bare scalar, which is legal JSON on its own", () => {
    render(<JsonView value="just a string" />);

    expect(screen.getByText("just a string")).toBeInTheDocument();
  });
});
