import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api-error";
import {
  TEACHING_POLL_MS,
  TEACHING_POLL_WINDOW_MS,
  initialTeachingReview,
  isTeachingId,
  teachingBudgetValid,
  teachingDeadlineLive,
  teachingDraftPending,
  teachingOrigin,
  teachingOrigins,
  teachingPathValid,
  teachingReason,
  teachingReviewIssue,
  type TeachingReviewIssue,
} from "./browser-teaching-review";
import {
  TEACHING_IDS as ids,
  teachingFixture,
  teachingReviewFixture,
} from "@/test-utils/browser-teaching";
import {
  TEACHING_REASONS,
  type BrowserTeaching,
  type TeachingReview,
} from "@/types/browser-teaching";

describe("teaching identity, freshness and safe reason presentation", () => {
  it("recognizes UUIDs without accepting additional path or whitespace", () => {
    expect(isTeachingId(ids.session)).toBe(true);
    expect(isTeachingId("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA")).toBe(true);
    for (const value of ["", "session", ids.session + "/other", " " + ids.session]) {
      expect(isTeachingId(value)).toBe(false);
    }
  });

  it("expires at the exact deadline and keeps polling finite", () => {
    const now = Date.parse("2030-01-01T00:00:00Z");
    expect(teachingDeadlineLive("2030-01-01T00:00:00.001Z", now)).toBe(true);
    expect(teachingDeadlineLive("2030-01-01T00:00:00Z", now)).toBe(false);
    expect(teachingDeadlineLive("2029-12-31T23:59:59Z", now)).toBe(false);
    expect(teachingDeadlineLive("invalid", now)).toBe(false);
    const clock = vi.spyOn(Date, "now").mockReturnValue(now);
    expect(teachingDeadlineLive("2030-01-02T00:00:00Z")).toBe(true);
    clock.mockRestore();
    expect(TEACHING_POLL_MS).toBe(2_000);
    expect(TEACHING_POLL_WINDOW_MS).toBe(180_000);
  });

  it("polls only queued or generating drafts", () => {
    expect(teachingDraftPending(undefined)).toBe(false);
    expect(teachingDraftPending(teachingFixture({ generation_state: "queued" }))).toBe(true);
    expect(teachingDraftPending(teachingFixture({ generation_state: "generating" }))).toBe(true);
    for (const generation_state of [
      "none",
      "succeeded",
      "refused",
      "unknown",
      "cancelled",
    ] as const) {
      expect(teachingDraftPending(teachingFixture({ generation_state }))).toBe(false);
    }
  });

  it.each(TEACHING_REASONS)("recognizes the closed server reason %s", (reason) => {
    expect(
      teachingReason(
        new ApiError(400, "Refused", {
          error: { code: "BAD_REQUEST", message: "Refused", details: { reason_code: reason } },
        }),
      ),
    ).toBe(reason);
  });

  it("does not display arbitrary error text or unknown reason codes as known reasons", () => {
    expect(teachingReason(new Error("private page text"))).toBeNull();
    expect(teachingReason(null)).toBeNull();
    expect(teachingReason(new ApiError(403, "Refused"))).toBeNull();
    for (const reason_code of [undefined, 42, "new_server_reason"]) {
      expect(
        teachingReason(
          new ApiError(400, "Refused", {
            error: { code: "BAD_REQUEST", message: "Refused", details: { reason_code } },
          }),
        ),
      ).toBeNull();
    }
  });
});

describe("review origin and path inputs", () => {
  it("derives only the HTTPS origin from the addressed browser URL", () => {
    expect(teachingOrigin("https://reports.example:8443/report?q=private#value")).toBe(
      "https://reports.example:8443",
    );
    expect(teachingOrigin("https://REPORTS.example:443/")).toBe("https://reports.example");
  });

  it.each([
    "not a URL",
    "http://reports.example",
    "https://name@reports.example",
    "https://:password@reports.example",
    "https://reports.example.",
  ])("refuses %s", (value) => {
    expect(teachingOrigin(value)).toBeNull();
  });

  it("accepts only distinct canonical origin lines within the explicit limit", () => {
    expect(teachingOrigins("\n https://reports.example \r\nhttps://second.example\n")).toEqual([
      "https://reports.example",
      "https://second.example",
    ]);
    expect(
      teachingOrigins(
        Array.from({ length: 10 }, (_, i) => "https://site" + i + ".example").join("\n"),
      ),
    ).toHaveLength(10);
    for (const value of [
      "",
      " \n",
      "https://reports.example\nhttps://reports.example",
      "https://reports.example/",
      "https://reports.example/private",
      "https://REPORTS.example",
      Array.from({ length: 11 }, (_, i) => "https://site" + i + ".example").join("\n"),
    ]) {
      expect(teachingOrigins(value)).toBeNull();
    }
  });

  it.each(["/", "/reports/{month}", "/reports/{month}/{month}", "/" + "a".repeat(511)])(
    "accepts a bounded reviewed path %s",
    (path) => {
      expect(teachingPathValid(path, new Set(["month"]))).toBe(true);
    },
  );

  it.each([
    "reports",
    "//reports.example/path",
    "/" + "a".repeat(512),
    "/reports?token=x",
    "/reports#token",
    "/reports%2fprivate",
    "/reports\\private",
    "/reports:private",
    "/reports@private",
    "/reports\u0000",
    "/reports\u001f",
    "/reports\u007f",
    "/./reports",
    "/reports/../private",
    "/{Missing}",
    "/{missing}",
    "/{month",
    "/month}",
    "/{a".padEnd(36, "a") + "}",
    "/{}",
  ])("refuses unsafe path %s", (path) => {
    expect(teachingPathValid(path, new Set(["month"]))).toBe(false);
  });

  it.each(["0.000001", "1", "1.000001", "10", "10.000000"])(
    "accepts the exact bounded budget %s",
    (value) => {
      expect(teachingBudgetValid(value)).toBe(true);
    },
  );
  it.each([
    "",
    "0",
    "0.000000",
    "-1",
    "10.000001",
    "11",
    "01",
    ".5",
    "1.",
    "1.0000001",
    "1e0",
    "Infinity",
    " 1",
    "1 ",
  ])("refuses ambiguous or out-of-range budget %s", (value) => {
    expect(teachingBudgetValid(value)).toBe(false);
  });
});

describe("complete review before draft consent", () => {
  it("requires a deliberate new review instead of copying page labels or values", () => {
    const session = teachingFixture();
    const result = initialTeachingReview(session);
    expect(result).toEqual({
      name: "",
      description: "",
      actions: session.events.map(({ sequence }) => ({
        sequence,
        label: "",
        parameter: null,
        path_template: null,
        omit: false,
      })),
      parameters: [],
      prerequisites: [],
      success_checks: [""],
    });
  });

  it("copies an existing saved review without sharing mutable state", () => {
    const review = teachingReviewFixture();
    const session = teachingFixture({ review });
    const result = initialTeachingReview(session);
    expect(result).toEqual(review);
    result.actions[0]!.label = "Changed locally";
    result.parameters[0]!.description = "Changed locally";
    expect(review.actions[0]!.label).toBe("Open reports");
    expect(review.parameters[0]!.description).toBe("The month to review");
  });

  it("accepts every reviewed event and explicit omissions with cleared optional fields", () => {
    const session = teachingFixture();
    const review = teachingReviewFixture();
    expect(teachingReviewIssue(session, review)).toBeNull();
    session.events[1]!.action = "select";
    expect(teachingReviewIssue(session, review)).toBeNull();
    review.actions[0] = { ...review.actions[0]!, omit: true, parameter: null, path_template: null };
    expect(teachingReviewIssue(session, review)).toBeNull();
  });

  type Case = {
    name: string;
    issue: TeachingReviewIssue;
    change: (session: BrowserTeaching, review: TeachingReview) => void;
  };
  const cases: Case[] = [
    {
      name: "empty slug",
      issue: "name",
      change: (_, r) => {
        r.name = "";
      },
    },
    {
      name: "slug grammar",
      issue: "name",
      change: (_, r) => {
        r.name = "Report Name";
      },
    },
    {
      name: "slug bound",
      issue: "name",
      change: (_, r) => {
        r.name = "a".repeat(65);
      },
    },
    {
      name: "blank description",
      issue: "description",
      change: (_, r) => {
        r.description = " ";
      },
    },
    {
      name: "description bound",
      issue: "description",
      change: (_, r) => {
        r.description = "a".repeat(501);
      },
    },
    {
      name: "empty recording",
      issue: "sequence",
      change: (s, r) => {
        s.events = [];
        r.actions = [];
      },
    },
    {
      name: "missing action",
      issue: "sequence",
      change: (_, r) => {
        r.actions.pop();
      },
    },
    {
      name: "changed sequence",
      issue: "sequence",
      change: (_, r) => {
        r.actions[0]!.sequence = 2;
      },
    },
    {
      name: "fractional sequence",
      issue: "sequence",
      change: (_, r) => {
        r.actions[0]!.sequence = 1.5;
      },
    },
    {
      name: "zero sequence",
      issue: "sequence",
      change: (_, r) => {
        r.actions[0]!.sequence = 0;
      },
    },
    {
      name: "sequence bound",
      issue: "sequence",
      change: (_, r) => {
        r.actions[0]!.sequence = 501;
      },
    },
    {
      name: "duplicate sequence",
      issue: "sequence",
      change: (s, r) => {
        s.events[1]!.sequence = 1;
        r.actions[1]!.sequence = 1;
      },
    },
    {
      name: "out-of-order sequence",
      issue: "sequence",
      change: (s, r) => {
        s.events.reverse();
        r.actions.reverse();
      },
    },
    {
      name: "action limit",
      issue: "sequence",
      change: (s, r) => {
        s.events = Array.from({ length: 501 }, (_, i) => ({ ...s.events[2]!, sequence: i + 1 }));
        r.actions = Array.from({ length: 501 }, (_, i) => ({ ...r.actions[2]!, sequence: i + 1 }));
      },
    },
    {
      name: "parameter limit",
      issue: "parameters",
      change: (_, r) => {
        r.parameters = Array.from({ length: 51 }, (_, i) => ({
          name: "p" + i,
          description: "Reviewed parameter",
        }));
      },
    },
    {
      name: "duplicate parameters",
      issue: "parameters",
      change: (_, r) => {
        r.parameters.push({ ...r.parameters[0]! });
      },
    },
    {
      name: "invalid parameter name",
      issue: "parameters",
      change: (_, r) => {
        r.parameters[0]!.name = "Month";
      },
    },
    {
      name: "blank parameter description",
      issue: "parameters",
      change: (_, r) => {
        r.parameters[0]!.description = " ";
      },
    },
    {
      name: "parameter description bound",
      issue: "parameters",
      change: (_, r) => {
        r.parameters[0]!.description = "a".repeat(241);
      },
    },
    {
      name: "blank action label",
      issue: "label",
      change: (_, r) => {
        r.actions[1]!.label = "";
      },
    },
    {
      name: "action label bound",
      issue: "label",
      change: (_, r) => {
        r.actions[1]!.label = "a".repeat(161);
      },
    },
    {
      name: "omitted label still required",
      issue: "label",
      change: (_, r) => {
        r.actions[0]!.omit = true;
        r.actions[0]!.label = "";
      },
    },
    {
      name: "omitted invalid parameter",
      issue: "parameter",
      change: (_, r) => {
        r.actions[1]!.omit = true;
        r.actions[1]!.parameter = "Month";
      },
    },
    {
      name: "omitted undeclared parameter",
      issue: "parameter",
      change: (_, r) => {
        r.actions[1]!.omit = true;
        r.actions[1]!.parameter = "other";
      },
    },
    {
      name: "omitted invalid path",
      issue: "path",
      change: (_, r) => {
        r.actions[0]!.omit = true;
        r.actions[0]!.path_template = "/?secret";
      },
    },
    {
      name: "omitted undeclared path parameter",
      issue: "path",
      change: (_, r) => {
        r.actions[0]!.omit = true;
        r.actions[0]!.path_template = "/{other}";
      },
    },
    {
      name: "input without parameter",
      issue: "parameter",
      change: (_, r) => {
        r.actions[1]!.parameter = null;
      },
    },
    {
      name: "click with parameter",
      issue: "parameter",
      change: (_, r) => {
        r.actions[2]!.parameter = "month";
      },
    },
    {
      name: "navigation without path",
      issue: "path",
      change: (_, r) => {
        r.actions[0]!.path_template = null;
      },
    },
    {
      name: "click with path",
      issue: "path",
      change: (_, r) => {
        r.actions[2]!.path_template = "/";
      },
    },
    {
      name: "all steps omitted",
      issue: "keptStep",
      change: (_, r) => {
        r.actions.forEach((a) => {
          a.omit = true;
        });
      },
    },
    {
      name: "prerequisite limit",
      issue: "prerequisites",
      change: (_, r) => {
        r.prerequisites = Array(17).fill("Reviewed prerequisite");
      },
    },
    {
      name: "blank prerequisite",
      issue: "prerequisites",
      change: (_, r) => {
        r.prerequisites = [" "];
      },
    },
    {
      name: "prerequisite bound",
      issue: "prerequisites",
      change: (_, r) => {
        r.prerequisites = ["a".repeat(241)];
      },
    },
    {
      name: "no success checks",
      issue: "successChecks",
      change: (_, r) => {
        r.success_checks = [];
      },
    },
    {
      name: "success check limit",
      issue: "successChecks",
      change: (_, r) => {
        r.success_checks = Array(17).fill("Reviewed success");
      },
    },
    {
      name: "blank success check",
      issue: "successChecks",
      change: (_, r) => {
        r.success_checks = [""];
      },
    },
    {
      name: "success check bound",
      issue: "successChecks",
      change: (_, r) => {
        r.success_checks = ["a".repeat(241)];
      },
    },
  ];
  it.each(cases)("refuses $name", ({ issue, change }) => {
    const session = teachingFixture();
    const review = teachingReviewFixture();
    change(session, review);
    expect(teachingReviewIssue(session, review)).toBe(issue);
  });

  it("accepts the maximum individual review field lengths", () => {
    const session = teachingFixture();
    const review = teachingReviewFixture();
    review.name = "a".repeat(64);
    review.description = "a".repeat(500);
    review.actions.forEach((action) => {
      action.label = "a".repeat(160);
    });
    review.parameters[0]!.description = "a".repeat(240);
    review.prerequisites = Array(16).fill("a".repeat(240));
    review.success_checks = Array(16).fill("a".repeat(240));
    expect(teachingReviewIssue(session, review)).toBeNull();
  });
});
