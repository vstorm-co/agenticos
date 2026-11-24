import { describe, expect, it } from "vitest";
import { applyBrowserFrame, protectBrowse } from "./browse";
import {
  BROWSER_PROCEDURE_TEACHING_IDS as ids,
  browserProcedureTeachingBrowseFixture,
} from "@/test-utils/browser-procedure-teaching";
import type { BrowserFrame } from "@/types/chat";

const frame = (data: Partial<BrowserFrame>): BrowserFrame => ({
  kind: "browser_procedure_teaching",
  call_id: "teaching-call",
  run_id: ids.run,
  tab_id: "main",
  step: 1,
  ...data,
});
describe("server-issued teaching state in a live browser", () => {
  it("accepts the exact current holder token and clears it when a different held event omits one", () => {
    const current = [browserProcedureTeachingBrowseFixture({ takeoverId: null })];
    const held = applyBrowserFrame(
      current,
      frame({ kind: "browser_held", by_user_id: ids.owner, takeover_id: ids.takeover }),
    );
    expect(held[0]?.takeoverId).toBe(ids.takeover);
    const changed = applyBrowserFrame(held, frame({ kind: "browser_held", by_user_id: ids.other }));
    expect(changed[0]).toMatchObject({ heldById: ids.other, takeoverId: null });
  });
  it.each(["browser_released", "browser_opened", "browser_finished"] as const)(
    "erases the lease on %s",
    (kind) => {
      const result = applyBrowserFrame(
        [browserProcedureTeachingBrowseFixture()],
        frame({ kind, outcome: "done" }),
      );
      expect(result[0]?.takeoverId).toBeNull();
    },
  );
  it("does not reacquire a lease after a browse finishes", () => {
    const stopped = browserProcedureTeachingBrowseFixture({
      outcome: "done",
      takeoverId: null,
      heldById: null,
    });
    expect(
      applyBrowserFrame([stopped], frame({ kind: "browser_held", takeover_id: ids.takeover }))[0],
    ).toBe(stopped);
  });
  it("retains only the newest notification for a known teaching session and reads no approval from it", () => {
    const current = [browserProcedureTeachingBrowseFixture()];
    const notified = applyBrowserFrame(
      current,
      frame({
        teaching_session_id: ids.session,
        teaching_status: "paused",
        teaching_revision: 4,
        teaching_reason: "paused_by_owner",
      }),
    );
    expect(notified[0]).toMatchObject({
      teachingSessionId: ids.session,
      teachingStatus: "paused",
      teachingRevision: 4,
      teachingReason: "paused_by_owner",
    });
    expect(
      applyBrowserFrame(
        notified,
        frame({
          teaching_session_id: ids.session,
          teaching_status: "recording",
          teaching_revision: 3,
        }),
      )[0],
    ).toBe(notified[0]);
    const next = applyBrowserFrame(notified, frame({ teaching_session_id: ids.other }));
    expect(next[0]).toMatchObject({
      teachingSessionId: ids.other,
      teachingStatus: null,
      teachingRevision: null,
      teachingReason: null,
    });
    expect(applyBrowserFrame(next, frame({}))[0]).toBe(next[0]);
  });
  it("drops a teaching notification for an unknown call or a different known run", () => {
    expect(applyBrowserFrame([], frame({ teaching_session_id: ids.session }))).toEqual([]);
    const current = [browserProcedureTeachingBrowseFixture()];
    expect(
      applyBrowserFrame(current, frame({ run_id: ids.other, teaching_session_id: ids.session })),
    ).toBe(current);
  });
  it("erases all teaching and holder metadata on protection, including late notifications", () => {
    const current = browserProcedureTeachingBrowseFixture({
      teachingSessionId: ids.session,
      teachingRevision: 5,
      teachingStatus: "recording",
      teachingReason: null,
    });
    const safe = protectBrowse(current);
    expect(safe).toMatchObject({
      takeoverId: null,
      teachingSessionId: null,
      teachingRevision: null,
      teachingStatus: null,
      teachingReason: null,
    });
    expect(
      applyBrowserFrame(
        [safe],
        frame({
          teaching_session_id: ids.session,
          teaching_revision: 6,
          teaching_status: "recording",
        }),
      )[0],
    ).toEqual(safe);
    expect(
      applyBrowserFrame([current], frame({ kind: "browser_protected", output_protected: true }))[0],
    ).toMatchObject({ outputProtected: true, takeoverId: null, teachingSessionId: null });
  });
});
