import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionPicker } from "./collection-picker";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import { useOrgStore } from "@/stores/org-store";
import type { KnowledgeBase } from "@/types/knowledge-base";

function collection(overrides: Partial<KnowledgeBase> = {}): KnowledgeBase {
  return {
    id: "kb-1",
    organization_id: "org-1",
    owner_user_id: null,
    name: "Handbook",
    description: null,
    scope: "org",
    collection_name: "handbook_a1b2c3",
    is_default: false,
    ingestion_config: DEFAULT_INGESTION_CONFIG,
    embedding_model: "text-embedding-3-large",
    embedding_provider: "openrouter",
    embedding_secret_id: null,
    embedding_endpoint_id: null,
    embedding_dim: 3072,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    document_count: 0,
    indexed_count: 0,
    chunk_count: 0,
    ...overrides,
  };
}

function mount(collections: KnowledgeBase[], selectedIds: string[] = [], disabled = false) {
  const onToggle = vi.fn();
  render(
    <CollectionPicker
      collections={collections}
      selectedIds={selectedIds}
      onToggle={onToggle}
      disabled={disabled}
    />,
  );
  return { onToggle };
}

describe("the collection picker", () => {
  beforeEach(() => useOrgStore.setState({ activeOrgId: "org-1" }));
  afterEach(() => useOrgStore.setState({ activeOrgId: null }));

  it("says an empty collection is empty", () => {
    // Attaching one produces an agent that searches, finds nothing and says so,
    // which reads as a broken agent rather than an empty collection. A name
    // alone cannot tell the two apart.
    mount([collection()]);

    expect(screen.getByText("empty")).toBeInTheDocument();
  });

  it("counts what a filled collection holds", () => {
    mount([collection({ document_count: 12, indexed_count: 12, chunk_count: 3402 })]);

    expect(screen.getByText("12 documents")).toBeInTheDocument();
    expect(screen.getByText("3,402 chunks")).toBeInTheDocument();
  });

  it("surfaces documents that never finished indexing", () => {
    // The two counts disagreeing is the only signal in a listing that a third of
    // the uploads died - the vectors they never wrote leave no other trace.
    mount([collection({ document_count: 12, indexed_count: 8, chunk_count: 200 })]);

    expect(screen.getByText("4 not indexed")).toBeInTheDocument();
  });

  it("says nothing about indexing when everything indexed", () => {
    // A "0 not indexed" line is an alarm about nothing, and a panel that always
    // looks slightly alarmed is one nobody reads.
    mount([collection({ document_count: 5, indexed_count: 5, chunk_count: 90 })]);

    expect(screen.queryByText(/not indexed/)).toBeNull();
  });

  it("names a collection the spec references but the organization no longer has", () => {
    // Publishing refuses it, and an id that silently vanishes from the form is
    // an id that is still in the spec.
    mount([collection()], ["kb-1", "kb-gone"]);

    expect(screen.getByText("kb-gone")).toBeInTheDocument();
  });

  it("shows the embedding model, because two collections built on different ones are not peers", () => {
    mount([collection()]);

    expect(screen.getByText("text-embedding-3-large")).toBeInTheDocument();
  });

  it("uses the singular for one document", () => {
    mount([collection({ document_count: 1, indexed_count: 1, chunk_count: 8 })]);

    expect(screen.getByText("1 document")).toBeInTheDocument();
  });

  it("counts more than one missing collection in the plural", () => {
    mount([collection()], ["kb-gone", "kb-also-gone"]);

    expect(screen.getByText(/2 collections this organization no longer has/)).toBeInTheDocument();
  });

  it("uses the singular for one missing collection", () => {
    mount([collection()], ["kb-gone"]);

    expect(screen.getByText(/1 collection this organization no longer has/)).toBeInTheDocument();
  });

  it("marks the default collection", () => {
    mount([collection({ is_default: true })]);

    expect(screen.getByText("default")).toBeInTheDocument();
  });

  it("shows a description when the collection has one", () => {
    mount([collection({ description: "Everything HR publishes." })]);

    expect(screen.getByText("Everything HR publishes.")).toBeInTheDocument();
  });

  it("says which collections are attached", () => {
    mount([collection(), collection({ id: "kb-2", name: "Contracts" })], ["kb-1"]);

    expect(screen.getByRole("checkbox", { name: "Handbook" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Contracts" })).not.toBeChecked();
  });

  it("shows the attached collections first", () => {
    mount([collection(), collection({ id: "kb-2", name: "Contracts" })], ["kb-2"]);

    const shown = screen.getAllByRole("checkbox").map((box) => box.getAttribute("aria-label"));
    expect(shown).toEqual(["Contracts", "Handbook"]);
  });

  it("toggles the collection that was pressed", async () => {
    const { onToggle } = mount([collection()]);

    await userEvent.click(screen.getByRole("checkbox", { name: "Handbook" }));

    expect(onToggle).toHaveBeenCalledWith("kb-1");
  });

  it("attaches nothing for a reader who may not edit the spec", async () => {
    const { onToggle } = mount([collection()], [], true);

    await userEvent.click(screen.getByRole("checkbox", { name: "Handbook" }));

    expect(onToggle).not.toHaveBeenCalled();
  });

  it("sends somebody to create a collection when the organization has none", () => {
    // The empty state is the finding: an agent with no collections searches
    // nothing, and the Knowledge page is where that is fixed.
    mount([]);

    expect(screen.getByText(/searches nothing/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Create one/ })).toBeInTheDocument();
  });

  it("offers a search only once the list is long enough to need one", async () => {
    const many = Array.from({ length: 9 }, (_, index) =>
      collection({ id: `kb-${index}`, name: index === 8 ? "Contracts" : `Handbook ${index}` }),
    );
    mount(many);

    await userEvent.type(screen.getByLabelText("Search collections…"), "contr");

    expect(screen.getByRole("checkbox", { name: "Contracts" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Handbook 0" })).toBeNull();
  });

  it("searches the description too, which is where the useful words are", async () => {
    const many = Array.from({ length: 9 }, (_, index) =>
      collection({
        id: `kb-${index}`,
        name: `Collection ${index}`,
        description: index === 3 ? "Signed customer contracts" : null,
      }),
    );
    mount(many);

    await userEvent.type(screen.getByLabelText("Search collections…"), "signed");

    expect(screen.getByRole("checkbox", { name: "Collection 3" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Collection 0" })).toBeNull();
  });

  it("distinguishes an upload in flight from one that died, by icon", () => {
    // Nothing indexed yet is a spinner; some indexed and some not is a warning.
    // The counts alone cannot tell those apart, which is why the icon differs.
    const { container } = render(
      <CollectionPicker
        collections={[collection({ document_count: 3, indexed_count: 0 })]}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );

    expect(container.querySelector(".animate-spin, .lucide-loader-circle")).not.toBeNull();
    expect(screen.getByText("3 not indexed")).toBeInTheDocument();
  });

  describe("for an agent, which cannot bind an app-scoped collection", () => {
    const appWide = collection({
      id: "kb-app",
      name: "Product manual",
      scope: "app",
      organization_id: null,
    });
    const mountFor = (selectedIds: string[], agentBindableOnly = true) => {
      const onToggle = vi.fn();
      render(
        <CollectionPicker
          collections={[collection(), appWide]}
          selectedIds={selectedIds}
          onToggle={onToggle}
          agentBindableOnly={agentBindableOnly}
        />,
      );
      return { onToggle };
    };

    it("leaves the app-scoped collection out of the offer", () => {
      mountFor([]);

      expect(screen.getByRole("checkbox", { name: "Handbook" })).toBeInTheDocument();
      expect(screen.queryByRole("checkbox", { name: "Product manual" })).toBeNull();
    });

    it("keeps one the spec already holds, says agents cannot use it, and lets it be removed", async () => {
      const { onToggle } = mountFor(["kb-app"]);

      const row = screen.getByRole("checkbox", { name: "Product manual" });
      expect(row).toHaveAttribute("aria-checked", "true");
      expect(screen.getByText("App-wide")).toBeInTheDocument();
      expect(
        screen.getByText(
          "App-wide knowledge bases can't be used by agents. Untick it to remove it.",
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText(/no longer has/)).toBeNull();
      await userEvent.click(row);
      expect(onToggle).toHaveBeenCalledWith("kb-app");
    });

    it("says there is nothing to attach when only app-scoped collections exist", () => {
      render(
        <CollectionPicker
          collections={[appWide]}
          selectedIds={[]}
          onToggle={vi.fn()}
          agentBindableOnly
        />,
      );

      expect(
        screen.getByText(
          "This organization has no collections yet. An agent with none searches nothing.",
        ),
      ).toBeInTheDocument();
    });

    it("still offers it to a workflow step, which reads it", () => {
      mountFor([], false);

      expect(screen.getByRole("checkbox", { name: "Product manual" })).toBeInTheDocument();
      expect(screen.queryByText("App-wide")).toBeNull();
    });
  });
  describe("for an agent, which cannot bind a personal collection from another organization", () => {
    const elsewhere = collection({
      id: "kb-elsewhere",
      name: "My notes",
      scope: "personal",
      organization_id: "org-2",
    });
    const mountFor = (selectedIds: string[], agentBindableOnly = true) => {
      const onToggle = vi.fn();
      render(
        <CollectionPicker
          collections={[collection({ scope: "personal" }), elsewhere]}
          selectedIds={selectedIds}
          onToggle={onToggle}
          agentBindableOnly={agentBindableOnly}
        />,
      );
      return { onToggle };
    };

    it("offers the personal collection made here and leaves out the one made elsewhere", () => {
      mountFor([]);

      expect(screen.getByRole("checkbox", { name: "Handbook" })).toBeInTheDocument();
      expect(screen.queryByRole("checkbox", { name: "My notes" })).toBeNull();
    });

    it("keeps one the spec already holds, says why agents cannot use it, and lets it be removed", async () => {
      const { onToggle } = mountFor(["kb-elsewhere"]);

      const row = screen.getByRole("checkbox", { name: "My notes" });
      expect(row).toHaveAttribute("aria-checked", "true");
      expect(screen.getByText("Another organization")).toBeInTheDocument();
      expect(
        screen.getByText(
          "This knowledge base belongs to another organization, so agents here can't use it. Untick it to remove it.",
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText("App-wide")).toBeNull();
      await userEvent.click(row);
      expect(onToggle).toHaveBeenCalledWith("kb-elsewhere");
    });

    it("still offers it to a workflow step, which reads it", () => {
      mountFor([], false);

      expect(screen.getByRole("checkbox", { name: "My notes" })).toBeInTheDocument();
      expect(screen.queryByText("Another organization")).toBeNull();
    });

    it("offers nothing until it knows which organization the agent is in", () => {
      useOrgStore.setState({ activeOrgId: null });
      mountFor(["kb-elsewhere"]);

      expect(screen.queryByRole("checkbox")).toBeNull();
      expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    });
  });
});
