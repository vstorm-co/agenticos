import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateSkillDialog } from "./create-skill-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    uploadMany: vi.fn(),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const TAKEN =
  "A skill named 'refund-policy' already exists. The name is how a model refers to a skill and cannot be changed afterwards, so choose a different one - or open the existing skill and edit it, which reaches every agent bound to it.";

const NAME_TAKEN = new ApiError(409, TAKEN, {
  error: { code: "ALREADY_EXISTS", message: TAKEN, details: { name: "refund-policy" } },
});

/** What a polyfilled `File.text()` should answer, per file. */
const bodies = new WeakMap<File, string>();

function textFile(path: string, body = "body"): File {
  const file = new File([body], path, { type: "text/markdown" });
  bodies.set(file, body);
  return file;
}

const name = () => screen.getByLabelText("Name");
const description = () => screen.getByLabelText("Description");
// The body is SKILL.md in the file pane, as the workbench has it - editable
// only once the pane is flipped to Source.
const content = () => screen.getByLabelText("SKILL.md source");
const create = () => screen.getByRole("button", { name: "Create" });

async function fill() {
  await userEvent.type(name(), "refund-policy");
  await userEvent.type(description(), "How refunds work.");
  await userEvent.click(screen.getByRole("button", { name: "Source" }));
  await userEvent.type(content(), "## Refunds");
}

/**
 * The same, for a dialog that already has a pending file.
 *
 * Adding one opens its pane, so the body has to be reopened before it can be
 * typed into - which is the flow a person goes through too.
 */
async function fillWithBody() {
  await userEvent.click(screen.getByRole("button", { name: "SKILL.md" }));
  await fill();
}

describe("CreateSkillDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [],
      total: 0,
      categories: ["ops-notes"],
      suggested_categories: ["marketing", "devops"],
    });
    render(<CreateSkillDialog open onOpenChange={vi.fn()} />, { wrapper });
  });

  it("lays the body out as SKILL.md, the way the editor will show it forever after", async () => {
    // The create form used to be the only place a skill did not look like a
    // folder. The second time anybody saw their skill it looked nothing like
    // the first - same tree, same pane, from the start.
    // Twice: once in the tree, once naming the open pane.
    expect(screen.getAllByText("SKILL.md")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Preview" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Source" })).toBeInTheDocument();
  });

  it("offers the shelves in use and the predefined ones, without constraining the field", async () => {
    // A select, so the list that already exists is visible before anybody
    // types - that is what keeps twenty skills off nineteen spellings of one
    // shelf. "New category…" is the way out: a category is the organization's
    // word, and anything typed stays as valid as anything picked.
    // Labels, not slugs: the stored value stays `ops-notes`, the reader sees
    // "Ops notes".
    await userEvent.click(screen.getByLabelText("Category"));
    expect(await screen.findByRole("option", { name: "Ops notes" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Marketing" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Devops" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("option", { name: "New category…" }));
    await userEvent.type(screen.getByLabelText("Category"), "something-nobody-suggested");
    expect(screen.getByLabelText("Category")).toHaveValue("something-nobody-suggested");
  });

  it("keeps the whole draft when the name is taken", async () => {
    // Content is a ten row editor. Losing it - or making somebody re-open a
    // dialog to find out what a toast said - is the cost of treating an
    // expected refusal as a failure.
    vi.mocked(apiClient.post).mockRejectedValue(NAME_TAKEN);
    await fill();
    await userEvent.click(create());

    await waitFor(() => expect(name()).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByText(TAKEN)).toBeInTheDocument();
    expect(content()).toHaveValue("## Refunds");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("tells the reader both ways out, in the server's own words", async () => {
    // The message is the product. A refusal that only states the fact leaves
    // somebody guessing whether a second skill or an edit is what they wanted.
    vi.mocked(apiClient.post).mockRejectedValue(NAME_TAKEN);
    await fill();
    await userEvent.click(create());

    await waitFor(() => expect(screen.getByText(TAKEN)).toBeInTheDocument());
    expect(screen.getByText(TAKEN)).toHaveTextContent("choose a different one");
    expect(screen.getByText(TAKEN)).toHaveTextContent("edit it");
  });

  it("puts a rejected length on the field it was rejected for", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(422, "…", {
        error: {
          code: "VALIDATION_ERROR",
          message: "description: String should have at most 500 characters",
          details: {
            fields: [
              { field: "description", message: "String should have at most 500 characters" },
            ],
          },
        },
      }),
    );
    await fill();
    await userEvent.click(create());

    await waitFor(() => expect(description()).toHaveAttribute("aria-invalid", "true"));
    expect(name()).not.toHaveAttribute("aria-invalid", "true");
  });

  it("marks the body itself when that is what the server refused", async () => {
    // The body lives in the file pane rather than beside the other fields, so a
    // refusal about it has to travel there - a red border on the description
    // would send somebody to rewrite the wrong thing.
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(422, "…", {
        error: {
          code: "VALIDATION_ERROR",
          message: "content: String should have at most 100000 characters",
          details: {
            fields: [{ field: "content", message: "String should have at most 100000 characters" }],
          },
        },
      }),
    );
    await fill();
    await userEvent.click(create());

    expect(
      await screen.findByText("String should have at most 100000 characters"),
    ).toBeInTheDocument();
  });

  it("does not let an over-long name leave the browser", async () => {
    expect(name()).toHaveAttribute("maxLength", "64");
    expect(description()).toHaveAttribute("maxLength", "500");
    // The category cap lives on the free-text field behind "New category…" -
    // the select's own options are already-valid names.
    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(screen.getByRole("option", { name: "New category…" }));
    expect(screen.getByLabelText("Category")).toHaveAttribute("maxLength", "64");
  });

  it("sends the category when one was picked", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "s1", name: "refund-policy" });
    await fill();
    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(screen.getByRole("option", { name: "New category…" }));
    await userEvent.type(screen.getByLabelText("Category"), "support");
    await userEvent.click(create());

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/skills",
        expect.objectContaining({ category: "support" }),
      ),
    );
  });

  it("sends no category rather than an empty one when the field is left blank", async () => {
    // "" is a category the backend refuses; a skill without one is
    // uncategorized, which is null.
    vi.mocked(apiClient.post).mockResolvedValue({ id: "s1", name: "refund-policy" });
    await fill();
    await userEvent.click(create());

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/skills",
        expect.objectContaining({ category: null }),
      ),
    );
  });
});

/**
 * The file side of the dialog.
 *
 * Files are local `File` objects until the skill exists, because a resource
 * hangs off a skill id - so creation is two writes, and the second one failing
 * must not pretend the first did not happen.
 */
describe("CreateSkillDialog files", () => {
  const onOpenChange = vi.fn();

  // jsdom's File does not implement `.text()`, which `PendingFilePane` uses to
  // read a pending file into the pane. Polyfilled rather than mocked away: the
  // read-and-show path is exactly what these assert.
  beforeAll(() => {
    if (typeof File.prototype.text !== "function") {
      Object.defineProperty(File.prototype, "text", {
        configurable: true,
        value(this: File) {
          return Promise.resolve(bodies.get(this) ?? "");
        },
      });
    }
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [],
      total: 0,
      categories: [],
      suggested_categories: ["devops"],
    });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "s-1", name: "refund-policy" });
    vi.mocked(apiClient.uploadMany).mockResolvedValue({ items: [] });
    render(<CreateSkillDialog open onOpenChange={onOpenChange} />, { wrapper });
  });

  it("cannot be created without a name and a description", async () => {
    // The description is the only part the model reads before deciding whether to
    // open the skill, so a skill without one is unreachable.
    expect(create()).toBeDisabled();

    await userEvent.type(name(), "refund-policy");
    expect(create()).toBeDisabled();

    await userEvent.type(description(), "How refunds work.");
    expect(create()).toBeEnabled();
  });

  it("sends a blank category as null rather than as an empty string", async () => {
    // The backend refuses `""` and takes null as uncategorised.
    await fill();
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills",
      expect.objectContaining({ category: null }),
    );
  });

  it("sends the shelf that was picked", async () => {
    // `CategoryInput` is a Select over the shelves already in use plus the
    // suggested ones - a free-text field would let two spellings of one shelf
    // exist, which is how a filter stops matching.
    await fill();
    await userEvent.click(screen.getByLabelText("Category"));
    // Shown humanised - a slug rendered raw reads as a leak from the database -
    // while the value sent stays the slug.
    await userEvent.click(screen.getByRole("option", { name: "Devops" }));
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills",
      expect.objectContaining({ category: "devops" }),
    );
  });

  it("closes on success", async () => {
    await fill();
    await userEvent.click(create());

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("uploads nothing when no file was added", async () => {
    await fill();
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(apiClient.uploadMany).not.toHaveBeenCalled();
  });

  it("adds a typed file to the tree and opens it", async () => {
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "references/a.md");
    await userEvent.type(screen.getByLabelText("File contents"), "body");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));

    expect(screen.getByText("a.md")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/uploads when the skill is created/)).toBeInTheDocument(),
    );
  });

  it("uploads the pending files once the skill exists", async () => {
    // Second write, after the id exists - there is nothing to attach them to
    // before this point.
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "a.md");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));
    await fillWithBody();
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.uploadMany).toHaveBeenCalled());
    const [path, files] = vi.mocked(apiClient.uploadMany).mock.calls.at(-1)!;
    expect(path).toBe("/skills/s-1/resources/upload");
    expect((files as File[])[0]!.name).toBe("a.md");
  });

  it("re-picking a path replaces it rather than adding a duplicate", async () => {
    // Somebody dropping a corrected file in means the corrected version.
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "a.md");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));

    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "a.md");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));

    // Counted in the tree: the open pane repeats the name in its header.
    expect(within(screen.getByRole("tree")).getAllByText("a.md")).toHaveLength(1);
  });

  it("removes a pending file", async () => {
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "a.md");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));

    expect(screen.queryByText("a.md")).toBeNull();
  });

  it("takes files from the picker", async () => {
    await userEvent.upload(screen.getByLabelText("Files"), textFile("picked.md"));

    expect(screen.getByText("picked.md")).toBeInTheDocument();
  });

  it("keeps a dropped folder's layout, because that is the path a resource takes", async () => {
    // A directory picker sends every file with its relative path; flattening it
    // would make `references/a.md` and `examples/a.md` the same resource.
    const nested = textFile("references/a.md", "one");
    Object.defineProperty(nested, "webkitRelativePath", { value: "references/a.md" });

    await userEvent.upload(screen.getByLabelText("Folder"), nested);

    expect(screen.getByText("a.md")).toBeInTheDocument();
  });

  it("shows a file whose read failed the same way as one it cannot show", async () => {
    // Either way the agent reads it as a file; what must not happen is a pane
    // that sits on "Loading…" forever because the read rejected.
    const unreadable = textFile("broken.md");
    Object.defineProperty(unreadable, "text", {
      configurable: true,
      value: () => Promise.reject(new Error("read failed")),
    });

    await userEvent.upload(screen.getByLabelText("Files"), unreadable);
    await userEvent.click(screen.getByText("broken.md"));

    expect(await screen.findByText(/Not shown here/)).toBeInTheDocument();
  });

  it("shows a file too large to preview as a file, not as half of one", async () => {
    // Reading half a megabyte into a pane to look at it is not worth the memory,
    // and the agent reads it as a file either way.
    const big = new File(["x".repeat(600_000)], "corpus.md", { type: "text/markdown" });
    await userEvent.upload(screen.getByLabelText("Files"), big);
    await userEvent.click(screen.getByText("corpus.md"));

    expect(screen.getByText(/Not shown here/)).toBeInTheDocument();
  });

  it("adds nothing when a picker is dismissed", () => {
    // What a cancelled file dialog looks like: the change fires with no files.
    fireEvent.change(screen.getByLabelText("Files"), { target: { files: [] } });

    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });

  it("closes without creating anything when cancelled", async () => {
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("shows a binary file as a fact rather than garbling it into a pane", async () => {
    // A PNG read as text is noise; the agent reads it as a file either way.
    // Picking a file adds it to the tree without opening it, so the pane is
    // reached by clicking the row.
    const binary = new File([new Uint8Array([0, 1, 2])], "logo.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("Files"), binary);
    await userEvent.click(screen.getByText("logo.png"));

    expect(screen.getByText(/Not shown here/)).toBeInTheDocument();
  });

  it("comes back to the body from a file", async () => {
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "a.md");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));

    await userEvent.click(screen.getByRole("button", { name: "SKILL.md" }));

    expect(screen.getByRole("button", { name: "SKILL.md" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("abandons the new-file form on cancel", async () => {
    await userEvent.click(screen.getByRole("button", { name: "New" }));

    // Two Cancels on screen - the dialog's and the form's. The form's is the one
    // inside the form.
    const form = screen.getByLabelText("Path").closest("form")!;
    await userEvent.click(within(form).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByLabelText("Path")).toBeNull();
  });

  it("says so when the skill was created but its files were not", async () => {
    // The skill exists. Pretending nothing happened would leave a half-made one
    // behind with no way to tell.
    vi.mocked(apiClient.uploadMany).mockRejectedValue(new Error("disk full"));
    await userEvent.click(screen.getByRole("button", { name: "New" }));
    await userEvent.type(screen.getByLabelText("Path"), "a.md");
    await userEvent.click(screen.getByRole("button", { name: "Add file" }));
    await fillWithBody();
    await userEvent.click(create());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    // The dialog stays open, so the failure is not dismissed along with it.
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("clears a field's refusal as soon as that field changes", async () => {
    // The refusal was about the value that was sent; it stops being true the
    // moment the value does.
    vi.mocked(apiClient.post).mockRejectedValueOnce(NAME_TAKEN);
    await fill();
    await userEvent.click(create());
    await waitFor(() => expect(name()).toHaveAttribute("aria-invalid", "true"));

    await userEvent.type(name(), "-2");

    expect(name()).not.toHaveAttribute("aria-invalid", "true");
  });
});
