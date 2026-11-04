import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Dialog, DialogContent, DialogTitle } from "./dialog";
import { Sheet, SheetContent, SheetTitle } from "./sheet";
import { useState } from "react";
import { Pager, SearchInput, useChosenFirst, useListControls } from "./list-controls";

const items = Array.from({ length: 120 }, (_, i) => `item ${i}`);
const matches = (item: string, query: string) => item.includes(query);

describe("useListControls", () => {
  it("shows one page at a time", () => {
    const { result } = renderHook(() => useListControls({ items, matches }));

    expect(result.current.visible).toHaveLength(50);
    expect(result.current.pageCount).toBe(3);
    expect(result.current.total).toBe(120);
  });

  it("moves to the next page", () => {
    const { result } = renderHook(() => useListControls({ items, matches }));

    act(() => result.current.setPage(1));

    expect(result.current.visible[0]).toBe("item 50");
  });

  it("goes back to the first page when the query changes", () => {
    // The bug this prevents: filtering to three results while sitting on page
    // four shows an empty list under a control that says there are three.
    const { result } = renderHook(() => useListControls({ items, matches }));

    act(() => result.current.setPage(2));
    act(() => result.current.setQuery("item 11"));

    expect(result.current.page).toBe(0);
    expect(result.current.visible.length).toBeGreaterThan(0);
  });

  it("clamps a page that no longer exists rather than rendering an empty one", () => {
    // Clamped on read, not corrected in an effect: an effect renders one frame
    // of the empty page first, which is the flicker.
    const { result, rerender } = renderHook(
      ({ list }) => useListControls({ items: list, matches }),
      { initialProps: { list: items } },
    );

    act(() => result.current.setPage(2));
    rerender({ list: items.slice(0, 10) });

    expect(result.current.page).toBe(0);
    expect(result.current.visible).toHaveLength(10);
  });

  it("reports how many survived the query, separately from how many there are", () => {
    const { result } = renderHook(() => useListControls({ items, matches }));

    act(() => result.current.setQuery("item 1"));

    expect(result.current.total).toBe(120);
    expect(result.current.matched).toBeLessThan(120);
  });

  it("folds case before matching, so a capitalised query still finds things", () => {
    const { result } = renderHook(() =>
      useListControls({
        items: ["Slack", "Notion"],
        matches: (i, q) => i.toLowerCase().includes(q),
      }),
    );

    act(() => result.current.setQuery("SLACK"));

    expect(result.current.visible).toEqual(["Slack"]);
  });
});

describe("Pager", () => {
  it("renders nothing at all when one page holds everything", () => {
    // A control that cannot do anything is one somebody reaches for anyway.
    const { container } = render(
      <Pager page={0} pageCount={1} matched={4} total={4} onPage={() => {}} counted="4 servers" />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("still reports a filtered count on a single page", () => {
    render(
      <Pager page={0} pageCount={1} matched={3} total={40} onPage={() => {}} counted="40 skills" />,
    );

    expect(screen.getByText("3 of 40 skills")).toBeInTheDocument();
  });

  it("frames the count it is handed and owns no noun of its own", () => {
    // What this replaces took `noun="skills"` and built `{matched} of {total}
    // {noun}`, so `3 of 40 skills` rendered verbatim under `pl` - English is the
    // only language where a noun beside a number needs no agreement. The noun
    // now arrives already inside an ICU plural, from the caller's namespace, and
    // the pager cannot tell one language from another.
    render(
      <Pager
        page={0}
        pageCount={2}
        matched={3}
        total={40}
        onPage={() => {}}
        counted="40 umiejętności"
      />,
    );

    expect(screen.getByText("3 of 40 umiejętności · page 1 of 2")).toBeInTheDocument();
  });

  it("moves a page when asked", async () => {
    const pages: number[] = [];
    render(
      <Pager
        page={1}
        pageCount={3}
        matched={120}
        total={120}
        onPage={(p) => pages.push(p)}
        counted="120 servers"
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await userEvent.click(screen.getByRole("button", { name: "Previous page" }));

    expect(pages).toEqual([2, 0]);
  });

  it("cannot step off either end", () => {
    render(
      <Pager
        page={0}
        pageCount={2}
        matched={60}
        total={60}
        onPage={() => {}}
        counted="60 skills"
      />,
    );

    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();
  });
});

describe("useChosenFirst", () => {
  const rows = ["a", "b", "c", "d"].map((id) => ({ id }));

  it("puts what is already chosen first, each half in its own order", () => {
    const { result } = renderHook(() => useChosenFirst(rows, ["d", "b"]));
    expect(result.current.map((row) => row.id)).toEqual(["b", "d", "a", "c"]);
  });

  it("keeps the order it opened with while somebody ticks and unticks", () => {
    const { result, rerender } = renderHook(({ chosen }) => useChosenFirst(rows, chosen), {
      initialProps: { chosen: ["c"] },
    });
    rerender({ chosen: ["c", "a"] });
    expect(result.current.map((row) => row.id)).toEqual(["c", "a", "b", "d"]);
  });
});

describe("SearchInput", () => {
  it("clears the query and keeps the input ready for another search", async () => {
    const change = vi.fn();
    render(<SearchInput value="invoice" onChange={change} placeholder="Find files…" />);
    await userEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(change).toHaveBeenCalledWith("");
    expect(screen.getByRole("textbox")).toHaveFocus();
  });

  it("uses Escape to clear before dismissing the surrounding panel", async () => {
    const change = vi.fn();
    const outer = vi.fn();
    const { rerender } = render(
      <div onKeyDown={outer}>
        <SearchInput value="invoice" onChange={change} placeholder="Find files…" />
      </div>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("textbox"));
    await user.keyboard("{Escape}");
    expect(change).toHaveBeenCalledWith("");
    expect(outer).not.toHaveBeenCalled();
    rerender(
      <div onKeyDown={outer}>
        <SearchInput value="" onChange={change} placeholder="Find files…" />
      </div>,
    );
    await user.keyboard("{Escape}");
    expect(outer).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Clear search" })).not.toBeInTheDocument();
  });
});

function SearchOverlay({ kind, close }: { kind: "sheet" | "dialog"; close: () => void }) {
  const [query, setQuery] = useState("invoice");
  const field = <SearchInput value={query} onChange={setQuery} placeholder="Find files…" />;
  return kind === "sheet" ? (
    <Sheet open onOpenChange={close}>
      <SheetContent>
        <SheetTitle>Files</SheetTitle>
        {field}
      </SheetContent>
    </Sheet>
  ) : (
    <Dialog open onOpenChange={close}>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle>Files</DialogTitle>
        {field}
      </DialogContent>
    </Dialog>
  );
}

it.each(["sheet", "dialog"] as const)(
  "clears on the first Escape inside an actual %s and dismisses on the second",
  async (kind) => {
    const close = vi.fn();
    render(<SearchOverlay kind={kind} close={close} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("textbox"));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(close).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    expect(close).toHaveBeenCalledWith(false);
  },
);
