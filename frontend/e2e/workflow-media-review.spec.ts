import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";
import type { ImageProvider } from "../src/hooks/use-model-providers";
import type {
  NodeDefinition,
  WorkflowDetail,
  WorkflowGraph,
  WorkflowMediaEstimateRead,
  WorkflowMediaEstimateRequest,
  WorkflowNodeRunRead,
  WorkflowRunFile,
  WorkflowRunRead,
} from "../src/lib/workflows/types";

test.use({ storageState: AUTH_STATE });

const workflowId = "8c82904c-cf95-44b0-81ae-6009f93aa001";
const runId = "8c82904c-cf95-44b0-81ae-6009f93aa002";
const nodeId = "8c82904c-cf95-44b0-81ae-6009f93aa003";
const nodeRunId = "8c82904c-cf95-44b0-81ae-6009f93aa004";
const at = "2026-11-16T08:00:00Z";
const secretId = "8c82904c-cf95-44b0-81ae-6009f93aa008";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGPwb/j/HwAFvgLOa7lHxwAAAABJRU5ErkJggg==",
  "base64",
);

const definition: NodeDefinition = {
  id: "image.generate",
  version: 1,
  name: "Generate image",
  category: "media",
  description: "Generate one image using a selected provider and a bounded reservation.",
  kind: "action",
  config_schema: { type: "object", properties: {} },
  input_schema: { type: "object", properties: {} },
  output_schema: { type: "object", properties: {} },
  ports: [
    { id: "in", label: "In", kind: "input", schema: null },
    { id: "out", label: "Out", kind: "output", schema: null },
  ],
  effect_kind: "write",
  retry_guarantee: "none",
  scopes: [],
  available: true,
};

const graph: WorkflowGraph = {
  entry_node_id: nodeId,
  nodes: [
    {
      id: nodeId,
      definition_id: definition.id,
      definition_version: 1,
      config: {},
      label: "Campaign image",
      layout: { x: 120, y: 120 },
    },
  ],
  edges: [],
  bindings: [],
  scopes: [],
};

const workflow: WorkflowDetail = {
  id: workflowId,
  slug: "media-review-fixture",
  name: "Campaign media review",
  description: "Synthetic media review fixture",
  status: "published",
  visibility: "private",
  owner_user_id: null,
  current_version_id: null,
  live_trigger: null,
  tags: [],
  trigger_active: null,
  draft_revision: 1,
  entry_node: definition.id,
  step_count: 1,
  last_run: null,
  created_at: at,
  updated_at: at,
  draft_graph: graph,
  can_edit: true,
  settings: {
    timezone: "UTC",
    default_deadline_seconds: null,
    error_workflow_id: null,
    error_workflow_run_as: null,
    run_retention_days: null,
    keep_succeeded_runs: true,
    max_concurrent_runs: null,
    run_budget_usd: 2,
    monthly_budget_usd: null,
  },
};

const run: WorkflowRunRead = {
  id: runId,
  workflow_id: workflowId,
  workflow_version_id: null,
  mode: "real",
  status: "failed",
  triggered_by: "manual",
  budget_limit: 2,
  spent_cost: 0.013,
  cost_is_partial: true,
  deadline_at: null,
  paused_reason: null,
  error: null,
  output: null,
  root_run_id: runId,
  causation_run_id: null,
  retry_of_run_id: null,
  depth: 0,
  can_cancel: true,
  started_at: at,
  ended_at: "2026-11-16T08:00:30Z",
  created_at: at,
};

const node: WorkflowNodeRunRead = {
  id: nodeRunId,
  node_instance_id: nodeId,
  scope_path: [],
  status: "failed",
  waiting_reason: null,
  attempts: 2,
  cost: 0.013,
  error: null,
  output: null,
  last_attempt_status: "uncertain",
  late_output: null,
  started_at: at,
  ended_at: run.ended_at,
  media_operation: {
    operation_id: "8c82904c-cf95-44b0-81ae-6009f93aa005",
    phase: "unknown",
    held_usd: "0.08",
    incurred_usd: "0.013",
    booked_usd: "0.013",
    node_unresolved_usd: "0.12",
    cost_source: "catalog_estimate",
    accounting_complete: false,
    has_receipt: false,
    retry_effect: "reconciliation_required",
  },
};

const files: [WorkflowRunFile, WorkflowRunFile] = [
  {
    id: "8c82904c-cf95-44b0-81ae-6009f93aa006",
    filename: "campaign-preview.png",
    content_type: "image/png",
    byte_size: png.length,
    producing_node_run_id: nodeRunId,
    created_at: at,
  },
  {
    id: "8c82904c-cf95-44b0-81ae-6009f93aa007",
    filename: "large-campaign.mp4",
    content_type: "video/mp4",
    byte_size: 65 * 1024 * 1024,
    producing_node_run_id: nodeRunId,
    created_at: at,
  },
];

const editorConfig = {
  provider: "openai",
  model: "review-image-model",
  secret_id: secretId,
  quality: "low",
  size: "1024x1024",
  output_format: "png",
  max_cost_usd: 0.25,
};

const imageProvider: ImageProvider = {
  provider: "openai",
  name: "OpenAI",
  models: [
    {
      id: "review-image-model",
      name: "Review image model",
      description: "Synthetic catalog entry for layout review",
      workflow: {
        reference_image: false,
        qualities: ["low", "medium", "high"],
        sizes: ["1024x1024"],
        aspect_ratios: [],
        backgrounds: [],
        output_formats: ["png", "jpeg"],
        defaults: {
          quality: "low",
          size: "1024x1024",
          aspect_ratio: null,
          background: null,
          output_format: "png",
        },
        max_input_tokens: 1024,
        max_output_tokens: 4096,
        input_usd_per_million: "2",
        output_usd_per_million: "10",
        tool_prompt_max_characters: 4000,
        tool_input_usd_per_million: "5",
        output_prices: [],
        pricing_as_of: "2026-11-16",
        sources: [],
      },
    },
  ],
};

const estimate: WorkflowMediaEstimateRead = {
  kind: "image",
  provider: "openai",
  model: "review-image-model",
  reservation_usd: "0.48",
  reserved_bytes: 10 * 1024 * 1024,
  pricing_as_of: "2026-11-16",
  configured_max_cost_usd: "0.25",
  sufficient_max_cost_usd: false,
  deficit_usd: "0.23",
  assumptions: [
    { code: "conservative_reservation" },
    { code: "single_submission" },
    { code: "image_token_ceiling", max_input_tokens: 1024, max_output_tokens: 4096 },
    { code: "unresolved_hold_retained" },
    { code: "dispatch_limits_rechecked" },
  ],
};

/** Every workflow request is answered here; no run, provider call or stored file is created. */
async function installReviewFixture(page: Page, editor = false) {
  const unexpected: string[] = [];
  const reads = { bytes: 0 };
  const estimates: WorkflowMediaEstimateRequest[] = [];
  const editorDefinition: NodeDefinition = {
    ...definition,
    config_schema: {
      type: "object",
      properties: {
        provider: { type: "string" },
        model: { type: "string" },
        secret_id: { type: "string" },
        max_cost_usd: { type: "number", title: "Maximum cost", minimum: 0 },
      },
    },
  };
  const editorGraph: WorkflowGraph = {
    ...graph,
    nodes: graph.nodes.map((entry) => ({ ...entry, config: editorConfig })),
  };
  const json = new Map<string, unknown>([
    ["/api/workflows/node-catalog", { items: [editor ? editorDefinition : definition], total: 1 }],
    [`/api/workflows/${workflowId}`, editor ? { ...workflow, draft_graph: editorGraph } : workflow],
    // The editor's version history: this draft has never been published.
    [`/api/workflows/${workflowId}/versions`, { items: [], next_before: null }],
    ["/api/workflow-approvals", { items: [], total: 0 }],
    ["/api/workflow-runs", { items: [], total: 0 }],
    [`/api/workflow-runs/${runId}`, run],
    [`/api/workflow-runs/${runId}/nodes`, { items: [node], total: 1 }],
    [`/api/workflow-runs/${runId}/graph`, { graph }],
    [`/api/workflow-runs/${runId}/files`, { items: files }],
    [`/api/workflow-runs/${runId}/logs`, { items: [], total: 0 }],
  ]);
  await page.route("**/api/workflow**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/\/$/, "");
    if (route.request().method() === "GET" && json.has(path)) {
      await route.fulfill({ json: json.get(path) });
    } else if (
      editor &&
      route.request().method() === "POST" &&
      path === "/api/workflows/media-estimate"
    ) {
      estimates.push(route.request().postDataJSON() as WorkflowMediaEstimateRequest);
      await route.fulfill({ json: estimate });
    } else if (
      route.request().method() === "GET" &&
      path === `/api/workflow-runs/${runId}/files/${files[0].id}`
    ) {
      reads.bytes += 1;
      await route.fulfill({
        body: png,
        contentType: "image/png",
        headers: { "Cache-Control": "private, no-store", "Content-Length": String(png.length) },
      });
    } else {
      unexpected.push(`${route.request().method()} ${path}`);
      await route.fulfill({ status: 400, json: { detail: "Unexpected media fixture request" } });
    }
  });
  if (editor) {
    await page.route("**/api/providers/image-models", async (route) => {
      if (route.request().method() !== "GET") {
        unexpected.push(`${route.request().method()} image-models`);
        await route.fulfill({ status: 400, json: { detail: "Read-only catalog fixture" } });
        return;
      }
      await route.fulfill({ json: { items: [imageProvider], total: 1 } });
    });
    await page.route("**/api/secrets**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(/\/$/, "");
      if (route.request().method() === "GET" && path === "/api/secrets") {
        await route.fulfill({
          json: {
            items: [
              {
                id: secretId,
                name: "Review organization key",
                kind: "api_key",
                purpose: "openai",
                usage_scope: "organization",
                hint: "fake",
                description: null,
                visibility: "private",
              },
            ],
            total: 1,
          },
        });
      } else if (route.request().method() === "GET" && path === "/api/secrets/kinds") {
        await route.fulfill({ json: { items: [], total: 0 } });
      } else {
        unexpected.push(`${route.request().method()} ${path}`);
        await route.fulfill({ status: 400, json: { detail: "Read-only key metadata fixture" } });
      }
    });
  }
  return { unexpected, reads, estimates };
}

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const) {
  test(`reviews a server media estimate without generating on ${viewport.name}`, async ({
    page,
  }, testInfo) => {
    testInfo.annotations.push({
      type: "visual-fixture",
      description:
        "Synthetic catalog, key metadata and estimate; no real key, write or provider call.",
    });
    const { unexpected, estimates } = await installReviewFixture(page, true);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(`/workflows/${workflowId}`);
    await page.getByText("Campaign image", { exact: true }).dblclick();
    const form = page.getByRole("dialog");
    const calculate = form.getByRole("button", { name: "Estimate reservation", exact: true });
    await expect(calculate).toBeEnabled();
    await expect(form).toContainText("Review organization key");
    expect(estimates).toEqual([]);
    await calculate.click();
    await expect(form).toContainText("Estimated reservation: $0.48");
    await expect(form).toContainText("Configured maximum cost: $0.25");
    await expect(form.getByRole("alert")).toContainText("The maximum cost is short by $0.23.");
    expect(estimates).toEqual([{ kind: "image", config: editorConfig }]);
    await form.getByText("How this is estimated", { exact: true }).click();
    await expect(form).toContainText("Reserved token limits: 1024 input and 4096 output tokens.");
    await expect(form).toContainText(
      "Unresolved charges stay reserved until they can be reconciled.",
    );
    await calculate.scrollIntoViewIfNeeded();
    await form.screenshot({ path: testInfo.outputPath(`media-estimate-${viewport.name}.png`) });
    expect(unexpected).toEqual([]);
  });

  test(`reviews media costs, fresh consent and file previews on ${viewport.name}`, async ({
    page,
  }, testInfo) => {
    testInfo.annotations.push({
      type: "visual-fixture",
      description:
        "Synthetic run journal and PNG; all workflow writes are blocked, no provider call.",
    });
    const { unexpected, reads } = await installReviewFixture(page);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(`/workflows/${workflowId}/runs/${runId}`);
    const operation = page.getByRole("region", { name: "Media operation", exact: true });
    await expect(operation).toContainText("Submission status unknown");
    await expect(operation).toContainText("Still reserved");
    await expect(operation).toContainText("Estimated incurred cost");
    await expect(operation).toContainText("Added to run spend");
    await expect(operation).toContainText("$0.0800");
    await expect(operation).toContainText(
      "Unresolved for this step, including earlier attempts: $0.1200",
    );
    await operation.screenshot({ path: testInfo.outputPath(`media-journal-${viewport.name}.png`) });

    await page.getByRole("button", { name: "Retry from failed step", exact: true }).click();
    const consent = page.getByRole("dialog", { name: "Start another run with media generation?" });
    const confirm = consent.getByRole("button", { name: "Start the new run", exact: true });
    const acknowledge = consent.getByRole("checkbox", {
      name: "I understand this can create another provider charge.",
    });
    await expect(confirm).toBeDisabled();
    await acknowledge.check();
    await expect(confirm).toBeEnabled();
    const box = await confirm.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
    await consent.screenshot({ path: testInfo.outputPath(`media-retry-${viewport.name}.png`) });
    await consent.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(consent).toBeHidden();
    await page.getByRole("button", { name: "Retry from failed step", exact: true }).click();
    await expect(acknowledge).not.toBeChecked();
    await expect(confirm).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(consent).toBeHidden();

    await page.getByRole("tab", { name: "Files", exact: true }).click();
    await expect(page.getByText("campaign-preview.png", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Preview large-campaign.mp4", exact: true }),
    ).toHaveCount(0);
    expect(reads.bytes).toBe(0);
    const preview = page.getByRole("button", { name: "Preview campaign-preview.png", exact: true });
    await preview.click();
    const viewer = page.getByRole("dialog", { name: /campaign-preview\.png/ });
    const picture = viewer.getByRole("img", { name: "campaign-preview.png", exact: true });
    await expect(picture).toBeVisible();
    await expect
      .poll(() => picture.evaluate((element) => (element as HTMLImageElement).naturalWidth))
      .toBe(1);
    const firstUrl = await picture.getAttribute("src");
    expect(firstUrl).toMatch(/^blob:/);
    expect(reads.bytes).toBe(1);
    await viewer.screenshot({ path: testInfo.outputPath(`media-preview-${viewport.name}.png`) });
    await page.keyboard.press("Escape");
    await expect(viewer).toBeHidden();
    await preview.click();
    await expect(picture).toBeVisible();
    await expect(picture).not.toHaveAttribute("src", firstUrl!);
    expect(reads.bytes).toBe(2);
    await page.keyboard.press("Escape");
    await expect(viewer).toBeHidden();
    expect(unexpected).toEqual([]);
  });
}
