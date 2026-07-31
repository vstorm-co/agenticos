import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillLibraryGallery } from "./skill-library-gallery";

interface LibraryEntry {
  key: string;
  name: string;
  description: string;
  installed: boolean;
  resources: { name: string; size_bytes: number }[];
}

const state = {
  library: [] as LibraryEntry[],
  isLoading: false,
  install: { mutate: vi.fn(), isPending: false },
};

vi.mock("@/hooks", () => ({ useSkillLibrary: () => state }));

function entry(overrides: Partial<LibraryEntry> = {}): LibraryEntry {
  const name = overrides.name ?? "code-review";
  return {
    key: name,
    name,
    description: `What ${name} is for.`,
    installed: false,
    resources: [],
    ...overrides,
  };
}

beforeEach(() => {
  state.library = [entry()];
  state.isLoading = false;
  state.install = { mutate: vi.fn(), isPending: false };
});

describe("the ready-made skills gallery", () => {
  it("shows a placeholder while the library loads", () => {
    state.isLoading = true;
    render(<SkillLibraryGallery canInstall />);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders nothing once everything on the shelf is installed", () => {
    // The section answers "what else could I have". A card for something
    // installed last week answers nothing - it used to be a second copy of the
    // list above, greyed out, with a button that did nothing when pressed.
    state.library = [entry({ installed: true })];
    const { container } = render(<SkillLibraryGallery canInstall />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the deployment ships no library at all", () => {
    state.library = [];
    const { container } = render(<SkillLibraryGallery canInstall />);

    expect(container).toBeEmptyDOMElement();
  });

  it("offers only what is not already installed", () => {
    state.library = [entry({ name: "kept" }), entry({ name: "already", installed: true })];
    render(<SkillLibraryGallery canInstall />);

    expect(screen.getByText("kept")).toBeInTheDocument();
    expect(screen.queryByText("already")).toBeNull();
  });

  it("says what a skill is for, which is what the choice is made on", () => {
    render(<SkillLibraryGallery canInstall />);

    expect(screen.getByText("What code-review is for.")).toBeInTheDocument();
  });

  it("lists the files a skill brings with it, and their size", () => {
    state.library = [entry({ resources: [{ name: "checklist.md", size_bytes: 2048 }] })];
    render(<SkillLibraryGallery canInstall />);

    expect(screen.getByText("checklist.md")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
  });

  it("installs the skill whose card was pressed", async () => {
    state.library = [entry({ name: "first" }), entry({ name: "second" })];
    render(<SkillLibraryGallery canInstall />);

    await userEvent.click(screen.getAllByRole("button", { name: "Install" })[1]!);

    expect(state.install.mutate).toHaveBeenCalledWith("second");
  });

  it("stops a second install while one is in flight", () => {
    state.install = { mutate: vi.fn(), isPending: true };
    render(<SkillLibraryGallery canInstall />);

    expect(screen.getByRole("button", { name: "Install" })).toBeDisabled();
  });

  it("shows the shelf without an install button to somebody who may not write skills", () => {
    // Reading what the deployment offers is not the same as installing it, and a
    // button that 403s is worse than no button.
    render(<SkillLibraryGallery canInstall={false} />);

    expect(screen.getByText("code-review")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Install" })).toBeNull();
  });

  it("offers no search box over a short shelf", () => {
    // A box over three cards reads as a missing list.
    render(<SkillLibraryGallery canInstall />);

    expect(screen.queryByPlaceholderText("Search library…")).toBeNull();
  });

  it("offers search once the shelf is long enough to need it", () => {
    state.library = Array.from({ length: 9 }, (_, index) => entry({ name: `skill-${index}` }));
    render(<SkillLibraryGallery canInstall />);

    expect(screen.getByPlaceholderText("Search library…")).toBeInTheDocument();
  });

  it("searches the description as well as the name", async () => {
    // Somebody looking for "refund" is looking for what the skill does, and has
    // no reason to know it is filed as `support-policy`.
    state.library = [
      ...Array.from({ length: 8 }, (_, index) => entry({ name: `filler-${index}` })),
      entry({ name: "support-policy", description: "How refunds are decided." }),
    ];
    render(<SkillLibraryGallery canInstall />);

    await userEvent.type(screen.getByPlaceholderText("Search library…"), "refund");

    expect(screen.getByText("support-policy")).toBeInTheDocument();
    expect(screen.queryByText("filler-0")).toBeNull();
  });
});
