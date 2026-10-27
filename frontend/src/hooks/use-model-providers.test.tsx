import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useImageProviders,
  useModelProviders,
  useProviderModels,
  useTextToSpeechProviders,
  useVideoProviders,
  useSpeechToTextProviders,
} from "./use-model-providers";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args), error: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useModelProviders", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("creates a model against a chosen key", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ label: "Claude (prod)" });
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createProfile.mutateAsync({
      label: "Claude (prod)",
      provider: "anthropic",
      model: "claude-sonnet-4-6",
      secret_id: "s1",
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      "/providers/model-profiles",
      expect.objectContaining({ model: "claude-sonnet-4-6", secret_id: "s1" }),
    );
  });

  it("surfaces a refused removal instead of leaving the row in place silently", async () => {
    // The server refuses deleting a profile an agent still points at, and the
    // panel's only way to say so is the toast.
    const { toast } = await import("sonner");
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("A published agent uses this model"));
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(result.current.deleteProfile.mutateAsync("p1")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("A published agent uses this model");
  });

  it("does not call an empty list of models the organization's answer when the read failed", async () => {
    // `profiles` degrades to `[]` either way, so a caller reading it as "this
    // organization has no model" would say that about a 502. `profilesStatus`
    // is the difference, and only the successful read carries `loaded`.
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      path === "/providers/model-profiles"
        ? Promise.reject(new Error("upstream timed out"))
        : Promise.resolve({ items: [], total: 0 }),
    );
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.profiles).toEqual([]);
    expect(result.current.profilesStatus).toBe("failed");
  });

  it("separates a read still in flight from one that failed", async () => {
    // The third state, and the one a pair of booleans loses: a cold render is
    // `[]` too, and a caller that only knew "not loaded" would raise a failure
    // on the ordinary path - every first paint of the Builder.
    let answer: (value: { items: []; total: number }) => void = () => {};
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      path === "/providers/model-profiles"
        ? new Promise((resolve) => {
            answer = resolve;
          })
        : Promise.resolve({ items: [], total: 0 }),
    );
    const { result } = renderHook(() => useModelProviders(), { wrapper });

    expect(result.current.profiles).toEqual([]);
    expect(result.current.profilesStatus).toBe("pending");

    answer({ items: [], total: 0 });
    await waitFor(() => expect(result.current.profilesStatus).toBe("loaded"));
  });

  it("calls an empty list the organization's answer when the read succeeded", async () => {
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.profilesStatus).toBe("loaded"));

    expect(result.current.profiles).toEqual([]);
  });

  it.each([null, "https://gateway.example/v1"])(
    "reclassifies saved models after a late listing without overriding endpoint %s",
    async (baseUrl) => {
      const listing = Promise.withResolvers<{
        items: { id: string; name: string; chat_capable: boolean }[];
        total: number;
        source: string;
      }>();
      vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
        if (path === "/providers/openrouter/models") return listing.promise;
        if (path === "/providers/model-profiles") {
          return {
            items: [
              {
                id: "p1",
                label: "Painter",
                provider: "openrouter",
                model: "acme/painter",
                base_url: baseUrl,
                secret_id: "s1",
                params: {},
                fallback_profile_ids: [],
                chat_capable: true,
              },
            ],
            total: 1,
          };
        }
        return { items: [], total: 0 };
      });
      const { result } = renderHook(
        () => {
          const profiles = useModelProviders();
          useProviderModels("openrouter");
          return profiles;
        },
        { wrapper },
      );
      await waitFor(() => expect(result.current.profilesStatus).toBe("loaded"));
      expect(result.current.profiles[0]?.chat_capable).toBe(true);

      await act(async () =>
        listing.resolve({
          items: [{ id: "acme/painter", name: "Painter", chat_capable: false }],
          total: 1,
          source: "live",
        }),
      );
      await waitFor(() => expect(result.current.profiles[0]?.chat_capable).toBe(baseUrl !== null));
      // A different API replica can still answer unknown. The browser's known
      // listing must continue to apply after such a refetch.
      await act(async () => {
        await result.current.refetchProfiles();
      });
      expect(result.current.profiles[0]?.chat_capable).toBe(baseUrl !== null);
      expect(
        vi
          .mocked(apiClient.get)
          .mock.calls.filter(([path]) => path === "/providers/openrouter/models"),
      ).toHaveLength(1);
    },
  );

  it.each([false, true])(
    "can refetch an observed listing once, including on failure: %s",
    async (fails) => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      function localWrapper({ children }: { children: ReactNode }) {
        return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
      }
      let listingCalls = 0;
      vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
        if (path === "/providers/model-profiles") {
          return {
            items: [
              {
                id: "p1",
                label: "Chat",
                provider: "openrouter",
                model: "acme/chat",
                secret_id: "s1",
                params: {},
                fallback_profile_ids: [],
              },
            ],
            total: 1,
          };
        }
        if (path === "/providers/openrouter/models") {
          listingCalls += 1;
          if (fails && listingCalls > 1) throw new Error("listing unavailable");
          return {
            items: [{ id: "acme/chat", name: "Chat", chat_capable: true }],
            total: 1,
            source: "live",
          };
        }
        return { items: [], total: 0 };
      });
      const { result } = renderHook(
        () => {
          const listing = useProviderModels("openrouter");
          const profiles = useModelProviders();
          return { listing, profiles };
        },
        { wrapper: localWrapper },
      );
      await waitFor(() => expect(result.current.profiles.profilesStatus).toBe("loaded"));
      await waitFor(() => expect(result.current.listing.models).toHaveLength(1));

      await act(async () => {
        await client.invalidateQueries({ queryKey: qk.providers.models("openrouter") });
      });

      expect(
        vi
          .mocked(apiClient.get)
          .mock.calls.filter(([path]) => path === "/providers/openrouter/models"),
      ).toHaveLength(2);
      expect(client.getQueryState(qk.providers.models("openrouter"))?.status).toBe(
        fails ? "error" : "success",
      );
    },
  );

  it("waits for refreshed provider metadata even with a cached listing", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(qk.providers.models("openrouter"), {
      items: [],
      total: 0,
      source: "live",
    });
    const listing = Promise.withResolvers<{ items: never[]; total: number; source: string }>();
    vi.mocked(apiClient.get).mockReturnValue(listing.promise);
    function localWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    }
    const { result } = renderHook(() => useProviderModels("openrouter"), { wrapper: localWrapper });
    expect(result.current.isLoading).toBe(false);
    let refresh: Promise<void> | undefined;
    act(() => {
      refresh = client.invalidateQueries({ queryKey: qk.providers.models("openrouter") });
    });
    await waitFor(() => expect(result.current.isLoading).toBe(true));
    await act(async () => {
      listing.resolve({ items: [], total: 0, source: "live" });
      await refresh;
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
  });

  it("changes a model in place, keeping its id", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "p1", label: "OpenAI · gpt-5" });
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.updateProfile.mutateAsync({ id: "p1", changes: { secret_id: "s2" } });

    expect(apiClient.patch).toHaveBeenCalledWith("/providers/model-profiles/p1", {
      secret_id: "s2",
    });
    expect(toastSuccess).toHaveBeenCalledWith("Updated OpenAI · gpt-5");
  });

  function inUse(agents: { id: string; name: string; archived?: boolean }[], hidden: number) {
    return new ApiError(409, "in use", {
      error: { code: "IN_USE", message: "in use", details: { agents, hidden_agents: hidden } },
    });
  }

  it("names the agents a refused removal is still used by (#2478)", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "p1", label: "OpenAI · gpt-5", provider: "openai", model: "gpt-5" }],
      total: 1,
    });
    vi.mocked(apiClient.delete).mockRejectedValue(
      inUse(
        [
          { id: "a1", name: "Helpdesk" },
          { id: "a2", name: "Researcher", archived: true },
        ],
        1,
      ),
    );
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.profiles).toHaveLength(1));

    await expect(result.current.deleteProfile.mutateAsync("p1")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith(
      "OpenAI · gpt-5 is still used by Helpdesk, Researcher and one agent you cannot see. " +
        "Move them to another model first, or change this model's key instead of deleting it. " +
        "One of them is archived: delete it, or restore it and move it.",
    );
  });

  it("counts the agents a refusal could not name", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "p9", label: "Haiku", provider: "anthropic", model: "claude-haiku-5" }],
      total: 1,
    });
    vi.mocked(apiClient.delete).mockRejectedValue(inUse([], 2));
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.profiles).toHaveLength(1));

    await expect(result.current.deleteProfile.mutateAsync("p9")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith(
      "Haiku is still used by 2 agents you cannot see. " +
        "Ask an admin to move them to another model first.",
    );
  });

  it("falls back on the server's sentence for a model the list no longer holds", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.delete).mockRejectedValue(
      new ApiError(409, "Model 'Old' is used by 1 agent: Helpdesk.", {
        error: {
          code: "IN_USE",
          message: "Model 'Old' is used by 1 agent: Helpdesk.",
          details: { agents: [{ id: "a1", name: "Helpdesk" }], hidden_agents: 0 },
        },
      }),
    );
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(result.current.deleteProfile.mutateAsync("gone")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("Model 'Old' is used by 1 agent: Helpdesk.");
  });

  it("removes a model", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useModelProviders(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.deleteProfile.mutateAsync("p1");
    expect(apiClient.delete).toHaveBeenCalledWith("/providers/model-profiles/p1");
  });
});

/**
 * The dropdown behind the model-id field.
 *
 * Suggestions, never a constraint: a provider ships a model the morning after
 * this list was cached, so the field stays free text and an unreachable provider
 * has to degrade to an empty list rather than to an error.
 */
describe("useProviderModels", () => {
  beforeEach(() => vi.clearAllMocks());

  it("reads the models one provider offers", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "gpt-5", name: "GPT-5", context_length: 400_000 }],
      total: 1,
      source: "live",
    });

    const { result } = renderHook(() => useProviderModels("openai"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/providers/openai/models");
    expect(result.current.models).toHaveLength(1);
    expect(result.current.source).toBe("live");
  });

  it("leaves out a model the platform knows an agent cannot run on", async () => {
    // Both fields this fills choose a model to talk to (#2487); a model the
    // server did not classify stays, because unknown is never a refusal.
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        { id: "gpt-5", name: "GPT-5", chat_capable: true },
        { id: "gpt-4o-mini-tts", name: "gpt-4o-mini-tts", chat_capable: false },
        { id: "unclassified", name: "unclassified" },
      ],
      total: 3,
      source: "live",
    });

    const { result } = renderHook(() => useProviderModels("openai"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.models.map((entry) => entry.id)).toEqual(["gpt-5", "unclassified"]);
    expect(result.current.refused).toEqual(["gpt-4o-mini-tts"]);
  });

  it("says the list is this deployment's own when the provider published none", () => {
    // The field's helper text differs: a curated list is worth saying out loud,
    // because a model missing from it is not a model that does not exist.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0, source: "curated" });

    const { result } = renderHook(() => useProviderModels("ollama"), { wrapper });

    return waitFor(() => expect(result.current.source).toBe("curated"));
  });

  it("does not fetch before a provider is chosen", () => {
    renderHook(() => useProviderModels(""), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("degrades to an empty list when the provider cannot be reached", async () => {
    // An empty dropdown is the state the field is built for; an error would put a
    // failure banner over a form that works perfectly well without suggestions.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("upstream timed out"));

    const { result } = renderHook(() => useProviderModels("openai"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.models).toEqual([]);
    expect(result.current.source).toBeNull();
  });
});

describe("useImageProviders", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks the platform which providers can draw and what with", async () => {
    // A catalog, not a listing: no credential is read, and the answer combines
    // what the SDK says a provider can do with what the catalog file offers.
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        {
          provider: "openai",
          name: "OpenAI",
          models: [{ id: "gpt-image-2", name: "GPT Image 2", description: "The best one." }],
        },
      ],
      total: 1,
    });
    const { result } = renderHook(() => useImageProviders(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/providers/image-models");
    expect(result.current.providers[0]?.models[0]?.name).toBe("GPT Image 2");
  });

  it("answers with an empty list and says it failed, rather than throwing", async () => {
    // The picker draws an explanation from this; a hook that threw would take the
    // whole capability panel with it.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useImageProviders(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.providers).toEqual([]);
  });
});

describe("useTextToSpeechProviders", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks the platform which providers can speak, with which models and voices", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        {
          provider: "elevenlabs",
          name: "ElevenLabs",
          formats: ["mp3", "wav"],
          account_voices: true,
          models: [],
        },
      ],
      total: 1,
    });
    const { result } = renderHook(() => useTextToSpeechProviders(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/providers/text-to-speech-models");
    expect(result.current.providers[0]?.account_voices).toBe(true);
  });

  it("answers with an empty list and says it failed, rather than throwing", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useTextToSpeechProviders(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.providers).toEqual([]);
  });
});

describe("useVideoProviders", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks the platform which providers can make video and what each model makes", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ provider: "xai", name: "xAI (Grok)", models: [] }],
      total: 1,
    });
    const { result } = renderHook(() => useVideoProviders(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/providers/video-models");
    expect(result.current.providers[0]?.provider).toBe("xai");
  });

  it("answers with an empty list and says it failed, rather than throwing", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useVideoProviders(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.providers).toEqual([]);
  });
});

describe("useSpeechToTextProviders", () => {
  beforeEach(() => vi.clearAllMocks());

  it("passes on the languages a recording may be pinned to", async () => {
    // The organization's Voice card offers exactly these, so the list is the
    // server's and not a copy kept here.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0, languages: ["en", "pl"] });
    const { result } = renderHook(() => useSpeechToTextProviders(), { wrapper });

    await waitFor(() => expect(result.current.languages).toEqual(["en", "pl"]));
    expect(apiClient.get).toHaveBeenCalledWith("/providers/speech-to-text-models");
  });

  it("answers with no providers and no languages when the catalog cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("502"));
    const { result } = renderHook(() => useSpeechToTextProviders(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.providers).toEqual([]);
    expect(result.current.languages).toEqual([]);
  });
});
