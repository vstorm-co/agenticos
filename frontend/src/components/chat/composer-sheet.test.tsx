import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Gauge } from "lucide-react";

import { ComposerSheet, SheetRow } from "./composer-sheet";

// Two triggers are drawn and CSS shows one: the menu's at a desk, the sheet's on a
// phone. jsdom applies no CSS, so the tests pick them by order.
const deskPlus = () => screen.getAllByRole("button", { name: "Add to message" })[0]!;
const phonePlus = () => screen.getAllByRole("button", { name: "Add to message" })[1]!;

describe("the composer's `+` at a desk", () => {
  it("names each action and says what it does", async () => {
    const onAttach = vi.fn();
    render(<ComposerSheet onAttach={onAttach} onVoice={vi.fn()} onCommand={vi.fn()} />);

    await userEvent.click(deskPlus());
    const attach = await screen.findByRole("menuitem", { name: /Attach file/ });
    expect(attach).toHaveTextContent("Images, PDFs, spreadsheets and documents");
    expect(screen.getByRole("menuitem", { name: /Commands/ })).toBeInTheDocument();

    await userEvent.click(attach);
    expect(onAttach).toHaveBeenCalledOnce();
  });

  it("offers no commands where the composer has none", async () => {
    render(<ComposerSheet onAttach={vi.fn()} onVoice={vi.fn()} />);

    await userEvent.click(deskPlus());
    await screen.findByRole("menuitem", { name: /Attach file/ });
    expect(screen.queryByRole("menuitem", { name: /Commands/ })).toBeNull();
  });
});

describe("starting a chat in a project", () => {
  it("is offered while the chat has not started, and only then", async () => {
    const onProject = vi.fn();
    const { unmount } = render(
      <ComposerSheet onAttach={vi.fn()} onVoice={vi.fn()} onProject={onProject} />,
    );
    await userEvent.click(deskPlus());
    await userEvent.click(await screen.findByRole("menuitem", { name: /Work in a project/ }));
    expect(onProject).toHaveBeenCalledOnce();
    unmount();

    render(<ComposerSheet onAttach={vi.fn()} onVoice={vi.fn()} />);
    await userEvent.click(deskPlus());
    await screen.findByRole("menuitem", { name: /Attach file/ });
    expect(screen.queryByRole("menuitem", { name: /Work in a project/ })).toBeNull();
  });
});

describe("the phone composer's sheet", () => {
  it("opens from its `+` and closes on the action picked", () => {
    const onAttach = vi.fn();
    const onVoice = vi.fn();
    const onCommand = vi.fn();
    render(<ComposerSheet onAttach={onAttach} onVoice={onVoice} onCommand={onCommand} />);
    expect(screen.queryByRole("dialog")).toBeNull();

    // Where a file comes from, as three tiles.
    for (const [tile, source] of [
      ["Camera", "camera"],
      ["Photos", "photos"],
      ["Files", "files"],
    ] as const) {
      fireEvent.click(phonePlus());
      fireEvent.click(screen.getByRole("button", { name: tile }));
      expect(onAttach).toHaveBeenLastCalledWith(source);
      expect(screen.queryByRole("dialog")).toBeNull();
    }

    fireEvent.click(phonePlus());
    fireEvent.click(screen.getByRole("button", { name: /Voice input/ }));
    expect(onVoice).toHaveBeenCalledOnce();

    fireEvent.click(phonePlus());
    fireEvent.click(screen.getByRole("button", { name: /Commands/ }));
    expect(onCommand).toHaveBeenCalledOnce();
  });

  it("closes on its own button, and lists the composer's other controls as rows", () => {
    render(
      <ComposerSheet
        onAttach={vi.fn()}
        phoneRows={
          <SheetRow icon={Gauge} label="Context used">
            <span>1.2%</span>
          </SheetRow>
        }
      />,
    );

    fireEvent.click(phonePlus());
    expect(screen.getByText("Context used")).toBeInTheDocument();
    expect(screen.getByText("1.2%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is a full-width sheet up from the bottom edge, clear of the home indicator", () => {
    render(<ComposerSheet onAttach={vi.fn()} onVoice={vi.fn()} />);

    fireEvent.click(phonePlus());

    expect(screen.getByRole("dialog")).toHaveClass(
      "inset-x-0",
      "bottom-[max(0px,calc(100dvh-var(--app-height,100dvh)))]",
      "pb-[var(--safe-bottom)]",
    );
  });

  it("cannot be opened while the composer is disabled", () => {
    render(<ComposerSheet onAttach={vi.fn()} onVoice={vi.fn()} disabled />);

    expect(deskPlus()).toBeDisabled();
    expect(phonePlus()).toBeDisabled();
  });
});
