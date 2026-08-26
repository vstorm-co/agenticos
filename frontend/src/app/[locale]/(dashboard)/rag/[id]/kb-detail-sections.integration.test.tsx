import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import KBDetailPage from "./page";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import { useOrgStore } from "@/stores";
import type { KBDocument, KnowledgeBase } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), raw: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// Key-returning translator: the refresh-failure assertions name message keys, rather
// than the sentences `messages/en.json` holds for them.
//
// One function per namespace, cached, because the real `useTranslations` is a `useMemo`
// over stable inputs. `useKBDetail` puts `t` in `refresh`'s dependencies and the page
// runs `useEffect(() => refresh(), [refresh])`, so a translator rebuilt per call made
// that effect re-fire forever and every test here timed out (#446).
//
// `rich`/`markup`/`has` hang off the same function, because a component under this
// tree reads a message with a tag in it; a mock modelling only part of `t` fails
// as `t.rich is not a function` inside a render, several files from the assertion
// (#612). The shared `keyTranslations` carries all three; the cache keeps the same
// `t` reference per namespace, which is what stops the effect above re-firing.
vi.mock("next-intl", async () => {
  const build = (await import("@/test-utils/intl")).keyTranslations((ns, key) => `${ns}.${key}`);
  const cache = new Map<string, ReturnType<typeof build>>();
  return {
    useLocale: () => "en",
    useTranslations: (ns: string) => {
      let translate = cache.get(ns);
      if (translate === undefined) {
        translate = build(ns);
        cache.set(ns, translate);
      }
      return translate;
    },
  };
});

const perms = new Set<string>(["collections:view"]);
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (p: string) => perms.has(p) }),
}));

const ORG_ID = "org-1";
const KB_ID = "5eacffcc-873e-42fe-a73a-32cd19322d00";

const KB: KnowledgeBase = {
  id: KB_ID,
  name: "Handbook",
  description: null,
  collection_name: "handbook",
  scope: "org",
  organization_id: ORG_ID,
  owner_user_id: null,
  is_default: false,
  ingestion_config: DEFAULT_INGESTION_CONFIG,
  embedding_model: "text-embedding-3-large",
  embedding_provider: "openrouter",
  embedding_secret_id: null,
  embedding_dim: 3072,
  rerank_model: null,
  rerank_secret_id: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: null,
  document_count: 0,
  indexed_count: 0,
  chunk_count: 0,
};

const DOC: KBDocument = {
  id: "doc-1",
  collection_name: "handbook",
  filename: "onboarding.md",
  filetype: "md",
  filesize: 2048,
  status: "done",
  error_message: null,
  vector_document_id: "vec-1",
  chunk_count: 4,
  has_file: true,
  created_at: "2026-07-01T00:00:00Z",
  completed_at: "2026-07-01T00:00:10Z",
  parser: "pymupdf",
  image_description_model: null,
  embedding_model: "text-embedding-3-large",
  was_overridden: false,
};

/**
 * Answer the detail page's fan-out, with one section's request failing.
 *
 * The order of the checks matters: `/sync-sources/connectors` and
 * `/sync-sources/org-integrations` both start with the plain
 * `/sync-sources` path.
 */
function mockApi({
  failing,
  documents = [],
  syncSources = [],
}: {
  failing?: "sync-sources" | "connectors" | "documents";
  documents?: KBDocument[];
  syncSources?: { id: string; name: string }[];
} = {}) {
  vi.mocked(apiClient.get).mockImplementation((endpoint: string) => {
    if (endpoint === `/kb/${KB_ID}`) return Promise.resolve(KB);
    if (endpoint.startsWith(`/kb/${KB_ID}/documents`)) {
      return failing === "documents"
        ? Promise.reject(new Error("Bad gateway"))
        : Promise.resolve({ items: documents, total: documents.length });
    }
    if (endpoint === `/kb/${KB_ID}/sync-sources/connectors`) {
      return failing === "connectors"
        ? Promise.reject(new Error("Bad gateway"))
        : Promise.resolve({ items: [] });
    }
    if (endpoint === `/kb/${KB_ID}/sync-sources/org-integrations`) {
      return Promise.resolve({ items: [], total: 0 });
    }
    if (endpoint === `/kb/${KB_ID}/sync-sources`) {
      return failing === "sync-sources"
        ? Promise.reject(new Error("Bad gateway"))
        : Promise.resolve({ items: syncSources, total: syncSources.length });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
}

/**
 * A pre-fulfilled thenable, so `use(params)` reads it synchronously instead of
 * suspending - the same fast path React takes once a promise has settled.
 */
function fulfilled<T>(value: T): Promise<T> {
  const thenable = Promise.resolve(value) as Promise<T> & { status: string; value: T };
  thenable.status = "fulfilled";
  thenable.value = value;
  return thenable;
}

/**
 * Select a section's tab.
 *
 * The three sections are tabs since #939, so a test asserting on the sync
 * sources has to choose that tab first - previously they were all stacked and
 * everything was on screen at once.
 */
async function openTab(name: string) {
  // `find`, not `get`: the page draws a skeleton until its collection arrives, so
  // a `get` here races the first render rather than the tab being absent.
  await userEvent.click(await screen.findByRole("tab", { name }));
}

async function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>
        <KBDetailPage params={fulfilled({ id: KB_ID })} />
      </Suspense>
    </QueryClientProvider>,
  );
  await act(async () => {});
  return view;
}

beforeEach(() => {
  // The page writes its tab into the URL, and jsdom's location persists across
  // tests in a file - so without this a test that opened Sync sources leaves the
  // next one mounting on that tab. A browser gets a fresh URL per navigation.
  window.history.replaceState({}, "", "/");
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: ORG_ID });
});

describe("a failed section renders an error, not its empty state (#32)", () => {
  it("a 502 on the sync sources renders the section's error state", async () => {
    mockApi({ failing: "sync-sources" });

    await renderPage();
    await openTab("pages.kb.syncSources");

    await waitFor(() =>
      expect(screen.getByText("pages.kb.syncSourcesFailedTitle")).toBeInTheDocument(),
    );
    expect(screen.queryByText("pages.kb.noSourcesConnected")).not.toBeInTheDocument();
    expect(screen.queryByText("pages.kb.noConnectorsConfigured")).not.toBeInTheDocument();
  });

  it("a 502 on the connectors renders an error, not 'no connectors configured'", async () => {
    mockApi({ failing: "connectors" });

    await renderPage();
    await openTab("pages.kb.syncSources");

    await waitFor(() =>
      expect(screen.getByText("pages.kb.connectorsFailedTitle")).toBeInTheDocument(),
    );
    expect(screen.queryByText("pages.kb.noConnectorsConfigured")).not.toBeInTheDocument();
  });

  it("a 502 on the connectors is still reported when sources already exist", async () => {
    mockApi({ failing: "connectors", syncSources: [{ id: "src-1", name: "Drive folder" }] });

    await renderPage();
    await openTab("pages.kb.syncSources");

    // The failure used to be reported only on the empty branch, so a base with
    // sources lost both the notice and - because the list is empty - the Connect
    // button, which reads as the product not offering connectors at all.
    await waitFor(() =>
      expect(screen.getByText("pages.kb.connectorsFailedTitle")).toBeInTheDocument(),
    );
    expect(screen.getByText("Drive folder")).toBeInTheDocument();
  });

  it("an actually empty answer still renders the empty state", async () => {
    mockApi();

    await renderPage();
    await openTab("pages.kb.syncSources");

    await waitFor(() =>
      expect(screen.getByText("pages.kb.noConnectorsConfigured")).toBeInTheDocument(),
    );
    expect(screen.queryByText("pages.kb.syncSourcesFailedTitle")).not.toBeInTheDocument();
    expect(screen.queryByText("pages.kb.connectorsFailedTitle")).not.toBeInTheDocument();
  });

  it("a 502 on the first load of the documents renders the page's error", async () => {
    mockApi({ failing: "documents" });

    await renderPage();

    // The documents query is load-bearing: it is not caught to an empty list, so
    // its failure takes the whole page rather than reading as "no documents".
    await waitFor(() => expect(screen.getByText("Bad gateway")).toBeInTheDocument());
    expect(screen.queryByText("pages.kb.noDocumentsYet")).not.toBeInTheDocument();
  });
});

describe("a failed refresh says so instead of ageing the page silently", () => {
  it("keeps the last good documents on screen and states that they may be stale", async () => {
    mockApi({ documents: [DOC] });

    await renderPage();
    await waitFor(() => expect(screen.getByText("onboarding.md")).toBeInTheDocument());
    expect(screen.queryByText("pages.kb.refreshFailedTitle")).not.toBeInTheDocument();

    // The refresh fails where the first load succeeded, so `kb` is already in hand.
    mockApi({ failing: "documents", documents: [DOC] });
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));

    await waitFor(() =>
      expect(screen.getByText("pages.kb.refreshFailedTitle")).toBeInTheDocument(),
    );
    expect(screen.getByText("pages.kb.refreshFailedDescription")).toBeInTheDocument();
    expect(screen.getByText("Bad gateway")).toBeInTheDocument();
    // Stale, and still there: blanking the list would read as "no documents".
    expect(screen.getByText("onboarding.md")).toBeInTheDocument();
  });
});

describe("the three sections are tabs (#939)", () => {
  it("shows the documents first and neither of the others", async () => {
    mockApi({ documents: [DOC] });

    await renderPage();

    await waitFor(() => expect(screen.getByText("onboarding.md")).toBeInTheDocument());
    // The parser panel and the sync sources are behind their own tabs, so
    // adjusting a parser no longer means scrolling past every document.
    expect(document.querySelector('[data-tour="kb-ingestion"]')).toBeNull();
    expect(screen.queryByText("pages.kb.noSourcesConnected")).not.toBeInTheDocument();
  });

  it("keeps the stats strip above them, because it describes the collection", async () => {
    // Not a tab's content: the document count and the scope are about the
    // collection, so they stay put whichever section is chosen.
    mockApi({ documents: [DOC] });

    await renderPage();
    const strip = await screen.findByText("pages.kb.scopeOrg");
    await openTab("pages.kb.syncSources");

    expect(strip).toBeInTheDocument();
  });

  it("shows one section at a time, and the parser panel is not one of the others", async () => {
    mockApi({ documents: [DOC] });

    await renderPage();
    await openTab("pages.kb.howDocumentsAreRead");

    await waitFor(() =>
      expect(document.querySelector('[data-tour="kb-ingestion"]')).not.toBeNull(),
    );
    // The documents table is gone rather than pushed down the page, which is the
    // whole point of the tabs.
    expect(screen.queryByText("onboarding.md")).not.toBeInTheDocument();
  });

  // The URL round-trip itself is `useUrlState`'s, and
  // `src/hooks/use-url-state.test.tsx` covers it - including a navigation that
  // changes the parameter under the state. Asserting it again here would mean
  // substituting either that hook or `useSearchParams`, and the global
  // `next/navigation` mock in `vitest.setup.ts` answers an empty one and wins:
  // a test written that way passed while the page was showing its default,
  // which is worse than not having it.
});
