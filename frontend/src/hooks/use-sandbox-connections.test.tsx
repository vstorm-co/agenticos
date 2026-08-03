import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useLocalSandboxService,
  useSandboxConnections,
  useSandboxEvents,
  useSandboxPolicy,
  useSandboxSessions,
} from "./use-sandbox-connections";
import * as api from "@/lib/sandbox-connections-api";
import type { SandboxConnectionRecord, SandboxPolicy } from "@/lib/sandbox-connections-api";

vi.mock("@/lib/sandbox-connections-api", () => ({
  listSandboxConnections: vi.fn(),
  createSandboxConnection: vi.fn(),
  updateSandboxConnection: vi.fn(),
  deleteSandboxConnection: vi.fn(),
  readSandboxPolicy: vi.fn(),
  listSandboxSessions: vi.fn(),
  readSandboxEvents: vi.fn(),
  readLocalSandboxService: vi.fn(),
  storeLocalSandboxCredential: vi.fn(),
  probeSandboxService: vi.fn(),
  listSandboxRuntimes: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function connection(overrides: Partial<SandboxConnectionRecord> = {}): SandboxConnectionRecord {
  return {
    id: "c-1",
    name: "Local Docker",
    kind: "docker",
    base_url: "http://sandboxd:8080",
    secret_id: "s-1",
    default_runtime: null,
    is_default: true,
    is_active: true,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

const POLICY: SandboxPolicy = {
  kind: "docker",
  runtimes: [
    {
      alias: "python",
      image: "python:3.12-slim",
      description: "",
      builds: false,
      mem_limit: "512m",
      cpus: 1,
      network_mode: "none",
    },
  ],
  default_runtime: "python",
  max_sessions: null,
  max_open_sessions: null,
  max_sessions_per_tenant: 5,
  idle_timeout: 900,
  workspace_root: null,
  persist_containers: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listSandboxConnections).mockResolvedValue([connection()]);
  vi.mocked(api.createSandboxConnection).mockResolvedValue(connection({ id: "c-2" }));
  vi.mocked(api.updateSandboxConnection).mockResolvedValue(connection());
  vi.mocked(api.deleteSandboxConnection).mockResolvedValue(undefined);
  vi.mocked(api.readSandboxPolicy).mockResolvedValue(POLICY);
  vi.mocked(api.listSandboxRuntimes).mockResolvedValue([
    { alias: "coding", description: "Python with git", image: "python:3.12-slim", builds: true },
  ]);
  vi.mocked(api.listSandboxSessions).mockResolvedValue({
    sessions: [],
    limit: 20,
    open_limit: null,
    tenant_limit: 5,
  });
  vi.mocked(api.readSandboxEvents).mockResolvedValue({ events: [], latest_seq: 0 });
});

describe("useSandboxConnections", () => {
  it("lists what the organization has registered", async () => {
    const { result } = renderHook(() => useSandboxConnections(), { wrapper });

    await waitFor(() => expect(result.current.connections).toHaveLength(1));
    expect(result.current.error).toBeNull();
  });

  it("refetches after every write, because promoting one demotes another", async () => {
    // Patching the edited row in place would leave two rows claiming to be the
    // default until something else refetched - and "which host does an agent
    // with no connection get" is exactly what this list answers.
    const { result } = renderHook(() => useSandboxConnections(), { wrapper });
    await waitFor(() => expect(result.current.connections).toHaveLength(1));

    await act(async () => {
      await result.current.create({ name: "Big box", kind: "docker", is_default: true });
    });

    expect(api.createSandboxConnection).toHaveBeenCalled();
    await waitFor(() => expect(api.listSandboxConnections).toHaveBeenCalledTimes(2));
  });

  it("refetches after an edit and after a delete too", async () => {
    const { result } = renderHook(() => useSandboxConnections(), { wrapper });
    await waitFor(() => expect(result.current.connections).toHaveLength(1));

    await act(async () => {
      await result.current.update("c-1", { name: "Renamed" });
    });
    await waitFor(() => expect(api.listSandboxConnections).toHaveBeenCalledTimes(2));

    await act(async () => {
      await result.current.remove("c-1");
    });
    await waitFor(() => expect(api.listSandboxConnections).toHaveBeenCalledTimes(3));
  });

  it("refreshing asks again", async () => {
    const { result } = renderHook(() => useSandboxConnections(), { wrapper });
    await waitFor(() => expect(result.current.connections).toHaveLength(1));

    await act(async () => {
      await result.current.refresh();
    });

    await waitFor(() => expect(api.listSandboxConnections).toHaveBeenCalledTimes(2));
  });

  it("says why the list is empty rather than leaving it looking registered-none", async () => {
    // An empty table and a failed request are the same pixels.
    vi.mocked(api.listSandboxConnections).mockRejectedValue(new Error("403 Forbidden"));
    const { result } = renderHook(() => useSandboxConnections(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("403 Forbidden"));
    expect(result.current.connections).toEqual([]);
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(api.listSandboxConnections).mockRejectedValue("nope");
    const { result } = renderHook(() => useSandboxConnections(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Failed to load sandbox connections"));
  });
});

describe("useSandboxPolicy", () => {
  it("asks the connection that was named", async () => {
    const { result } = renderHook(() => useSandboxPolicy("c-1"), { wrapper });

    await waitFor(() => expect(result.current.policy).toEqual(POLICY));
    expect(api.readSandboxPolicy).toHaveBeenCalledWith("c-1");
  });

  it("asks nothing until a connection is chosen", () => {
    // The Builder renders this before an author has picked a host, and a call
    // with no id would be a 404 on every keystroke.
    const { result } = renderHook(() => useSandboxPolicy(null), { wrapper });

    expect(api.readSandboxPolicy).not.toHaveBeenCalled();
    expect(result.current.policy).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it("reports a host that did not answer, rather than an empty allowlist", async () => {
    // "No runtimes" and "no answer" are different problems, and offering an
    // empty select for the second is how an author publishes an alias nothing
    // accepts.
    vi.mocked(api.readSandboxPolicy).mockRejectedValue(new Error("did not answer"));
    const { result } = renderHook(() => useSandboxPolicy("c-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("did not answer"));
    expect(result.current.policy).toBeNull();
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(api.readSandboxPolicy).mockRejectedValue("nope");
    const { result } = renderHook(() => useSandboxPolicy("c-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("The sandbox service did not answer"));
  });
});

describe("useSandboxSessions", () => {
  it("asks the connection that was named, without sampling usage", async () => {
    const { result } = renderHook(() => useSandboxSessions("c-1"), { wrapper });

    await waitFor(() => expect(result.current.listing?.tenant_limit).toBe(5));
    expect(api.listSandboxSessions).toHaveBeenCalledWith("c-1", false);
  });

  it("samples usage only when the caller opts in", async () => {
    const { result } = renderHook(() => useSandboxSessions("c-1", true), { wrapper });

    await waitFor(() => expect(result.current.listing).not.toBeNull());
    expect(api.listSandboxSessions).toHaveBeenCalledWith("c-1", true);
  });

  it("asks nothing for a deployment with no container connection", () => {
    const { result } = renderHook(() => useSandboxSessions(null), { wrapper });

    expect(api.listSandboxSessions).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
  });

  it("reports a host that did not answer rather than looking idle", async () => {
    vi.mocked(api.listSandboxSessions).mockRejectedValue(new Error("did not answer"));
    const { result } = renderHook(() => useSandboxSessions("c-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("did not answer"));
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(api.listSandboxSessions).mockRejectedValue("nope");
    const { result } = renderHook(() => useSandboxSessions("c-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("The sandbox service did not answer"));
  });
});

describe("useSandboxEvents", () => {
  it("reads the log of the session it was given", async () => {
    vi.mocked(api.readSandboxEvents).mockResolvedValue({
      events: [
        {
          seq: 1,
          at: 1,
          op: "exec",
          target: "python run.py",
          ok: true,
          detail: "",
          duration_ms: 5,
        },
      ],
      latest_seq: 1,
    });
    const { result } = renderHook(() => useSandboxEvents("c-1", "xc-1"), { wrapper });

    await waitFor(() => expect(result.current.log?.latest_seq).toBe(1));
    expect(api.readSandboxEvents).toHaveBeenCalledWith("c-1", "xc-1");
  });

  it("asks nothing until a session is chosen", () => {
    const { result } = renderHook(() => useSandboxEvents("c-1", null), { wrapper });

    expect(api.readSandboxEvents).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
  });

  it("reports a log that could not be read", async () => {
    vi.mocked(api.readSandboxEvents).mockRejectedValue(new Error("404 Not Found"));
    const { result } = renderHook(() => useSandboxEvents("c-1", "xc-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("404 Not Found"));
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(api.readSandboxEvents).mockRejectedValue("nope");
    const { result } = renderHook(() => useSandboxEvents("c-1", "xc-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("That activity log could not be read"));
  });
});

describe("what this deployment can already see", () => {
  it("asks nothing until a form that would use the answer is open", () => {
    // Editing an existing connection does not need it, and a probe is a round trip
    // to an address that usually is not there.
    renderHook(() => useLocalSandboxService(false), { wrapper });

    expect(api.readLocalSandboxService).not.toHaveBeenCalled();
  });

  it("reports what answered", async () => {
    vi.mocked(api.readLocalSandboxService).mockResolvedValue({
      url: "http://sandboxd:8080",
      token_available: true,
      registered_connection_id: null,
    });

    const { result } = renderHook(() => useLocalSandboxService(true), { wrapper });

    await waitFor(() => expect(result.current.local?.url).toBe("http://sandboxd:8080"));
  });

  it("treats nothing answering as an answer rather than an error", async () => {
    // A deployment running no sandbox service is the common case, and a red line
    // every time somebody opens the form would report a problem nobody has.
    vi.mocked(api.readLocalSandboxService).mockResolvedValue({
      url: null,
      token_available: false,
      registered_connection_id: null,
    });

    const { result } = renderHook(() => useLocalSandboxService(true), { wrapper });

    await waitFor(() => expect(result.current.local).not.toBeNull());
    expect(result.current.local?.url).toBeNull();
  });

  it("answers with the id of the stored token, and refreshes the vault list", async () => {
    // The credential picker reads that list, so the id it returns has to be
    // selectable in it.
    vi.mocked(api.readLocalSandboxService).mockResolvedValue({
      url: null,
      token_available: true,
      registered_connection_id: null,
    });
    vi.mocked(api.storeLocalSandboxCredential).mockResolvedValue({
      secret_id: "s-local",
      name: "Sandbox service token (this deployment)",
      hint: "4242",
    });

    const { result } = renderHook(() => useLocalSandboxService(true), { wrapper });

    await expect(result.current.storeCredential()).resolves.toBe("s-local");
  });

  it("passes a probe straight through, address and key", async () => {
    const { result } = renderHook(() => useLocalSandboxService(true), { wrapper });
    vi.mocked(api.probeSandboxService).mockResolvedValue(POLICY);

    await expect(result.current.probe("http://s:8080", "s-1")).resolves.toEqual(POLICY);
    expect(api.probeSandboxService).toHaveBeenCalledWith("http://s:8080", "s-1");
  });
});

describe("the runtime catalog", () => {
  it("is fetched whenever the form is open, not only for a new connection", async () => {
    // It is static for the life of the deployment and asks no host anything, so
    // there is nothing to save by withholding it from an edit.
    const { result } = renderHook(() => useLocalSandboxService(false), { wrapper });

    await waitFor(() => expect(result.current.runtimes).toHaveLength(1));
    expect(api.listSandboxRuntimes).toHaveBeenCalled();
  });

  it("answers with an empty list rather than failing the form", async () => {
    // A catalog request that failed must leave a usable text field behind, not an
    // unusable select.
    vi.mocked(api.listSandboxRuntimes).mockRejectedValue(new Error("nope"));

    const { result } = renderHook(() => useLocalSandboxService(true), { wrapper });

    await waitFor(() => expect(result.current.runtimes).toEqual([]));
  });
});
