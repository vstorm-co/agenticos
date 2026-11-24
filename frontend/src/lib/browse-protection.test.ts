import { describe, expect, it } from "vitest";
import {
  applyBrowserFrame,
  applyBrowserProtection,
  latestBrowserTabs,
  withLivePreview,
  type Browse,
} from "./browse";
import type { BrowserFrame } from "@/types/chat";

const frame = (overrides: Partial<BrowserFrame>): BrowserFrame => ({
  kind: "browser_frame",
  run_id: "run",
  call_id: "call",
  tab_id: "main",
  step: 2,
  ...overrides,
});

function page(callId = "call", runId = "run", tabId: string | null = "main"): Browse {
  return {
    callId,
    runId,
    tabId,
    goal: "Unrestricted task",
    maxSteps: 20,
    url: "https://portal.example/private?secret=old",
    title: "Private page",
    image: "data:image/jpeg;base64,OLD",
    imageStep: 5,
    steps: [
      {
        step: 4,
        operation: "type",
        target: "private label",
        reason: "raw reason",
        url: "https://portal.example/private",
      },
    ],
    needs: "raw request",
    heldBy: "Person",
    heldById: "user",
    nativeId: "native-window",
    resumable: true,
    navigable: true,
    controlError: "raw error",
    detail: "raw detail",
    kept: "saved sign-in",
    pointer: { x: 0.5, y: 0.5, step: 5 },
    outcome: null,
  };
}

const hidden = {
  outputProtected: true,
  goal: "",
  maxSteps: null,
  url: null,
  title: null,
  image: null,
  imageStep: -1,
  steps: [],
  needs: null,
  heldBy: null,
  heldById: null,
  nativeId: null,
  resumable: false,
  navigable: false,
  controlError: null,
  detail: null,
  kept: null,
  pointer: null,
};

describe("protected browser output", () => {
  it("scrubs a legacy cached entry when its first authoritative run and tab identity arrive", () => {
    const legacy = { ...page(), runId: undefined, tabId: undefined };
    const [protectedPage] = applyBrowserFrame([legacy], frame({ kind: "browser_protected" }));
    expect(protectedPage).toMatchObject({ ...hidden, runId: "run", tabId: "main" });
    expect(withLivePreview(legacy, protectedPage!)).toMatchObject({
      ...hidden,
      runId: "run",
      tabId: "main",
    });
    const [after] = applyBrowserFrame(
      [protectedPage!],
      frame({ kind: "browser_finished", outcome: undefined }),
    );
    expect(after).toMatchObject({ ...hidden, outcome: null });
  });
  it("erases the full cached preview before any later frame, while retaining safe routing and plan IDs", () => {
    const [protectedPage] = applyBrowserFrame(
      [page()],
      frame({
        kind: "browser_protected",
        credential_plan_id: "plan",
        credential_operation: "fill",
        image: "must not be used",
        url: "https://portal.example/reflection",
        title: "reflected value",
      }),
    );
    expect(protectedPage).toMatchObject({
      ...hidden,
      callId: "call",
      runId: "run",
      tabId: "main",
      credentialPlanId: "plan",
      credentialOperation: "fill",
    });
  });

  it.each([
    "browser_opened",
    "browser_frame",
    "browser_step",
    "browser_control_error",
    "browser_needs_person",
    "browser_pointer",
    "browser_held",
    "browser_released",
    "browser_finished",
  ] as const)(
    "never restores page output after a later %s, even when its protection flag is false",
    (kind) => {
      const before = applyBrowserFrame([page()], frame({ kind: "browser_protected" }));
      const [after] = applyBrowserFrame(
        before,
        frame({
          kind,
          output_protected: false,
          image: "late picture",
          url: "https://portal.example/leak",
          title: "late title",
          goal: "late goal",
          operation: "type",
          target: "late target",
          reason: "late reason",
          detail: "late detail",
          by: "person",
          by_user_id: "user",
          native_id: "native",
          navigable: true,
          resumable: true,
          outcome: "done",
        }),
      );
      expect(after).toMatchObject(hidden);
      expect(after?.outcome).toBe(kind === "browser_finished" ? "done" : null);
    },
  );

  it("honors the explicit flag on ordinary events and scrubs older calls on only the same run and tab", () => {
    const input = [
      page(),
      page("older"),
      page("another-tab", "run", "other"),
      page("another-run", "other-run"),
    ];
    const after = applyBrowserFrame(input, frame({ output_protected: true }));
    expect(after[0]).toMatchObject(hidden);
    expect(after[1]).toMatchObject(hidden);
    expect(after[2]).toBe(input[2]);
    expect(after[3]).toBe(input[3]);
    const added = applyBrowserFrame(
      after,
      frame({
        kind: "browser_opened",
        call_id: "next-call",
        output_protected: false,
        image: "old",
        url: "https://portal.example/leak",
        navigable: true,
      }),
    );
    expect(added.at(-1)).toMatchObject({ ...hidden, callId: "next-call" });
  });

  it("keeps unknown late calls out of the chat and does not infer a shared tab when IDs are absent", () => {
    expect(applyBrowserFrame([], frame({ kind: "browser_protected" }))).toEqual([]);
    const input = [page("known", "run", null), page("unrelated", "run", null)];
    const after = applyBrowserFrame(
      input,
      frame({
        kind: "browser_protected",
        call_id: "known",
        tab_id: undefined,
      }),
    );
    expect(after[0]).toMatchObject(hidden);
    expect(after[1]).toBe(input[1]);
  });

  it("lets a live snapshot scrub the retained chat cache, without creating a browse or touching another run", () => {
    const input = [page(), page("older"), page("different", "different")];
    const safe = applyBrowserProtection(input, { callId: "call", runId: "run" });
    expect(safe[0]).toMatchObject(hidden);
    expect(safe[1]).toMatchObject(hidden);
    expect(safe[2]).toBe(input[2]);
    expect(applyBrowserProtection([], { callId: "call", runId: "run" })).toEqual([]);
    expect(applyBrowserProtection(input, { callId: "call", runId: "wrong" })).toBe(input);
  });

  it("keeps protection through completed, missing and mismatched live-preview fallbacks", () => {
    const streamed = { ...page(), outcome: "done" as const };
    const protectedLive = { ...page(), outputProtected: true };
    expect(withLivePreview(streamed, protectedLive)).toMatchObject({ ...hidden, outcome: "done" });
    const protectedStream = { ...streamed, outputProtected: true };
    expect(withLivePreview(protectedStream, page())).toMatchObject(hidden);
    expect(withLivePreview(protectedStream, null)).toMatchObject(hidden);
    expect(withLivePreview(protectedStream, page("wrong"))).toMatchObject(hidden);
    expect(withLivePreview(page(), { ...protectedLive, runId: "wrong" })).toEqual(page());
  });

  it("retains the protected tab for its receipt while excluding an ordinary non-navigable trace", () => {
    const safe = applyBrowserFrame([page()], frame({ kind: "browser_protected" }));
    const trace = { ...page("trace", "run", "other"), navigable: false, nativeId: null };
    expect(latestBrowserTabs([trace, ...safe])).toEqual(safe);
  });
});
