import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api-error";
import {
  BROWSER_PROCEDURE_TEACHING_POLL_MS,
  BROWSER_PROCEDURE_TEACHING_POLL_WINDOW_MS,
  initialBrowserProcedureTeachingReview,
  isBrowserProcedureTeachingId,
  browserProcedureTeachingBudgetValid,
  browserProcedureTeachingDeadlineLive,
  browserProcedureTeachingDraftPending,
  browserProcedureTeachingOrigin,
  browserProcedureTeachingOrigins,
  browserProcedureTeachingPathValid,
  browserProcedureTeachingReason,
  browserProcedureTeachingReviewIssue,
  type BrowserProcedureTeachingReviewIssue,
} from "./browser-procedure-teaching-review";
import {
  BROWSER_PROCEDURE_TEACHING_IDS as ids,
  browserProcedureTeachingFixture,
  browserProcedureTeachingReviewFixture,
} from "@/test-utils/browser-procedure-teaching";
import {
  BROWSER_PROCEDURE_TEACHING_REASONS,
  type BrowserProcedureTeaching,
  type BrowserProcedureTeachingReview,
} from "@/types/browser-procedure-teaching";

describe("teaching identity, freshness and safe reason presentation", () => {
  it("recognizes UUIDs without accepting additional path or whitespace", () => {
    expect(isBrowserProcedureTeachingId(ids.session)).toBe(true);
    expect(isBrowserProcedureTeachingId("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA")).toBe(true);
    for (const value of ["", "session", ids.session + "/other", " " + ids.session]) {
      expect(isBrowserProcedureTeachingId(value)).toBe(false);
    }
  });

  it("expires at the exact deadline and keeps polling finite", () => {
    const now = Date.parse("2030-01-01T00:00:00Z");
    expect(browserProcedureTeachingDeadlineLive("2030-01-01T00:00:00.001Z", now)).toBe(true);
    expect(browserProcedureTeachingDeadlineLive("2030-01-01T00:00:00Z", now)).toBe(false);
    expect(browserProcedureTeachingDeadlineLive("2029-12-31T23:59:59Z", now)).toBe(false);
    expect(browserProcedureTeachingDeadlineLive("invalid", now)).toBe(false);
    const clock = vi.spyOn(Date, "now").mockReturnValue(now);
    expect(browserProcedureTeachingDeadlineLive("2030-01-02T00:00:00Z")).toBe(true);
    clock.mockRestore();
    expect(BROWSER_PROCEDURE_TEACHING_POLL_MS).toBe(2_000);
    expect(BROWSER_PROCEDURE_TEACHING_POLL_WINDOW_MS).toBe(180_000);
  });

  it("polls only queued or generating drafts", () => {
    expect(browserProcedureTeachingDraftPending(undefined)).toBe(false);
    expect(
      browserProcedureTeachingDraftPending(
        browserProcedureTeachingFixture({ generation_state: "queued" }),
      ),
    ).toBe(true);
    expect(
      browserProcedureTeachingDraftPending(
        browserProcedureTeachingFixture({ generation_state: "generating" }),
      ),
    ).toBe(true);
    for (const generation_state of [
      "none",
      "succeeded",
      "refused",
      "unknown",
      "cancelled",
    ] as const) {
      expect(
        browserProcedureTeachingDraftPending(browserProcedureTeachingFixture({ generation_state })),
      ).toBe(false);
    }
  });

  it.each(BROWSER_PROCEDURE_TEACHING_REASONS)(
    "recognizes the closed server reason %s",
    (reason) => {
      expect(
        browserProcedureTeachingReason(
          new ApiError(400, "Refused", {
            error: { code: "BAD_REQUEST", message: "Refused", details: { reason_code: reason } },
          }),
        ),
      ).toBe(reason);
    },
  );

  it("does not display arbitrary error text or unknown reason codes as known reasons", () => {
    expect(browserProcedureTeachingReason(new Error("private page text"))).toBeNull();
    expect(browserProcedureTeachingReason(null)).toBeNull();
    expect(browserProcedureTeachingReason(new ApiError(403, "Refused"))).toBeNull();
    for (const reason_code of [undefined, 42, "new_server_reason"]) {
      expect(
        browserProcedureTeachingReason(
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
    expect(
      browserProcedureTeachingOrigin("https://reports.example:8443/report?q=private#value"),
    ).toBe("https://reports.example:8443");
    expect(browserProcedureTeachingOrigin("https://REPORTS.example:443/")).toBe(
      "https://reports.example",
    );
  });

  it.each([
    "not a URL",
    "http://reports.example",
    "https://name@reports.example",
    "https://:password@reports.example",
    "https://reports.example.",
  ])("refuses %s", (value) => {
    expect(browserProcedureTeachingOrigin(value)).toBeNull();
  });

  it("accepts only distinct canonical origin lines within the explicit limit", () => {
    expect(
      browserProcedureTeachingOrigins("\n https://reports.example \r\nhttps://second.example\n"),
    ).toEqual(["https://reports.example", "https://second.example"]);
    expect(
      browserProcedureTeachingOrigins(
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
      expect(browserProcedureTeachingOrigins(value)).toBeNull();
    }
  });

  it.each(["/", "/reports/{month}", "/reports/{month}/{month}", "/" + "a".repeat(511)])(
    "accepts a bounded reviewed path %s",
    (path) => {
      expect(browserProcedureTeachingPathValid(path, new Set(["month"]))).toBe(true);
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
    expect(browserProcedureTeachingPathValid(path, new Set(["month"]))).toBe(false);
  });

  it.each(["0.000001", "1", "1.000001", "10", "10.000000"])(
    "accepts the exact bounded budget %s",
    (value) => {
      expect(browserProcedureTeachingBudgetValid(value)).toBe(true);
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
    expect(browserProcedureTeachingBudgetValid(value)).toBe(false);
  });
});

describe("complete review before draft consent", () => {
  it("requires a deliberate new review instead of copying page labels or values", () => {
    const session = browserProcedureTeachingFixture();
    const result = initialBrowserProcedureTeachingReview(session);
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
    const review = browserProcedureTeachingReviewFixture();
    const session = browserProcedureTeachingFixture({ review });
    const result = initialBrowserProcedureTeachingReview(session);
    expect(result).toEqual(review);
    result.actions[0]!.label = "Changed locally";
    result.parameters[0]!.description = "Changed locally";
    expect(review.actions[0]!.label).toBe("Open reports");
    expect(review.parameters[0]!.description).toBe("The month to review");
  });

  it("accepts every reviewed event and explicit omissions with cleared optional fields", () => {
    const session = browserProcedureTeachingFixture();
    const review = browserProcedureTeachingReviewFixture();
    expect(browserProcedureTeachingReviewIssue(session, review)).toBeNull();
    session.events[1]!.action = "select";
    expect(browserProcedureTeachingReviewIssue(session, review)).toBeNull();
    review.actions[0] = { ...review.actions[0]!, omit: true, parameter: null, path_template: null };
    expect(browserProcedureTeachingReviewIssue(session, review)).toBeNull();
  });

  type Case = {
    name: string;
    issue: BrowserProcedureTeachingReviewIssue;
    change: (session: BrowserProcedureTeaching, review: BrowserProcedureTeachingReview) => void;
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
    const session = browserProcedureTeachingFixture();
    const review = browserProcedureTeachingReviewFixture();
    change(session, review);
    expect(browserProcedureTeachingReviewIssue(session, review)).toBe(issue);
  });

  it("accepts the maximum individual review field lengths", () => {
    const session = browserProcedureTeachingFixture();
    const review = browserProcedureTeachingReviewFixture();
    review.name = "a".repeat(64);
    review.description = "a".repeat(500);
    review.actions.forEach((action) => {
      action.label = "a".repeat(160);
    });
    review.parameters[0]!.description = "a".repeat(240);
    review.prerequisites = Array(16).fill("a".repeat(240));
    review.success_checks = Array(16).fill("a".repeat(240));
    expect(browserProcedureTeachingReviewIssue(session, review)).toBeNull();
  });
});
