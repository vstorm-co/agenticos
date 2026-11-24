import { randomUUID } from "node:crypto";
import type { APIRequestContext } from "@playwright/test";
import type { RoomLeadPolicy, RoomRoutingProposal, RoomTaskCard } from "../src/types/room-routing";
import { expect, test } from "./fixtures";
import { AUTH_STATE, SEEDED_PROJECT_NAME, json } from "./helpers";

test.use({ storageState: AUTH_STATE });

async function findSeededRow(
  request: APIRequestContext,
  path: string,
  matches: (row: Record<string, unknown>) => boolean,
) {
  // Persistent E2E environments can place the seed beyond the default first 50 rows.
  for (let skip = 0; skip < 1000; skip += 100) {
    const page = await json<{ items: Record<string, unknown>[]; total: number }>(
      request,
      `${path}?limit=100&skip=${skip}`,
    );
    const row = page.items.find(matches);
    if (row) return row;
    if (page.items.length === 0 || skip + page.items.length >= page.total) return undefined;
  }
  throw new Error(`The visual fixture seed was not found within 1000 rows of ${path}`);
}

/**
 * Fixture-only visual evidence on the actual room screen. The room and its
 * membership are real; policy/proposal/task metadata are explicitly synthetic.
 * No provider is contacted, no message is sent and no task is created here.
 * Backend authority/dispatch acceptance is covered separately, not by these images.
 */
for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const) {
  test(`captures loaded room lead fixtures at ${viewport.name} width`, async ({
    page,
  }, testInfo) => {
    testInfo.annotations.push({
      type: "evidence",
      description:
        "Synthetic room routing metadata; visual fixture only, no provider/model invocation.",
    });
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const me = await json<{ id: string }>(page.request, "/api/auth/me");
    const project = await findSeededRow(
      page.request,
      "/api/projects",
      (row) => row.name === SEEDED_PROJECT_NAME,
    );
    expect(project, "the visual fixture requires the seeded project").toBeTruthy();
    const agent = await findSeededRow(
      page.request,
      "/api/agents",
      // The rule `roomResponders` applies: the seeded AgenticOS agent needs a local
      // coding agent, so a room cannot pick it as lead and the dialog would say so.
      (row) =>
        row.status === "published" &&
        row.can_run === true &&
        !row.local_workspace &&
        !row.local_coding_agent &&
        !row.personal_coding_harness,
    );
    expect(agent, "the visual fixture requires a seeded agent a room can pick").toBeTruthy();
    const leadName = String(agent!.name);
    expect(
      agent!.current_version_id,
      "the seeded room agent must have a valid published version",
    ).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
    const created = await page.request.post("/api/conversations", {
      data: { project_id: project!.id, title: `Room lead visual fixture (${viewport.name})` },
    });
    expect(created.ok(), "create only this owned visual-fixture room").toBe(true);
    const { id: roomId } = (await created.json()) as { id: string };
    const pin = {
      agent_id: String(agent!.id),
      version_id: String(agent!.current_version_id),
      name: String(agent!.name),
      current: true,
    };
    const policy: RoomLeadPolicy = {
      enabled: true,
      revision: 7,
      lead: pin,
      specialists: [pin],
      max_items: 3,
      can_edit: true,
      can_ask: true,
    };
    const proposal: RoomRoutingProposal = {
      id: randomUUID(),
      conversation_id: roomId,
      thread_root_message_id: null,
      submission_id: randomUUID(),
      message_id: randomUUID(),
      requester_id: me.id,
      lead_run_id: null,
      policy_revision: 7,
      revision: 1,
      decision: "pending",
      accepted_item_ids: [],
      can_accept: true,
      can_discard: true,
      created_at: "2026-11-16T00:00:00Z",
      items: [
        {
          proposal_item_id: randomUUID(),
          title: "Fixture: Reconcile the invoice batch",
          expected_result:
            "A checked reconciliation with discrepancies explained for human review.",
          accountable_user_id: randomUUID(),
          accountable_user_name: "Jordan (fixture)",
          due_at: "2026-11-17T09:00:00Z",
          agent: pin,
          existing_task_id: null,
          expected_task_revision: null,
        },
      ],
    };
    const task: RoomTaskCard = {
      id: randomUUID(),
      proposal_id: randomUUID(),
      proposal_item_id: randomUUID(),
      message_id: randomUUID(),
      thread_root_message_id: null,
      task_id: randomUUID(),
      table_id: randomUUID(),
      accepted_revision: 1,
      revision: 2,
      title: "Fixture: Review the prepared report",
      description: "The agent finished its run. A person still needs to review the result.",
      status: "waiting_for_user",
      next_actor: "user",
      accountable_user_id: me.id,
      accountable_user_name: null,
      agent: pin,
      due_at: "2026-11-17T11:00:00Z",
    };
    const unexpectedWrites: string[] = [];
    try {
      await page.route(`**/api/conversations/${roomId}/**`, async (route) => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        // Opening a room marks it read; that receipt is the room's own, not routing.
        if (request.method() === "POST" && path === `/api/conversations/${roomId}/read`)
          await route.fallback();
        else if (request.method() !== "GET") {
          unexpectedWrites.push(`${request.method()} ${path}`);
          await route.fulfill({ status: 403, json: { detail: "Visual fixture is read only" } });
        } else if (path.endsWith("/lead-policy")) await route.fulfill({ json: policy });
        else if (path.endsWith("/routing-proposals"))
          await route.fulfill({ json: { items: [proposal], has_more: false } });
        else if (path.endsWith("/task-links"))
          await route.fulfill({ json: { items: [task], has_more: false } });
        else await route.fallback();
      });
      await page.goto(`/chat?id=${roomId}`);
      await expect(page.getByRole("textbox", { name: "Message to the team" })).toBeEnabled();
      const panel = page.locator('[data-tour="chat-room-routing"]');
      await panel.getByRole("button", { name: /Lead & tasks/ }).click();
      await expect(panel.getByText(`Lead: ${leadName}`, { exact: true })).toBeVisible();
      const proposed = panel.getByRole("article", { name: "Task proposal", exact: true });
      await expect(proposed.getByText("Jordan (fixture)", { exact: true })).toBeVisible();
      await proposed
        .getByRole("checkbox", { name: "Fixture: Reconcile the invoice batch" })
        .check();
      await expect(
        proposed.getByRole("button", { name: "Accept selected", exact: true }),
      ).toBeEnabled();
      await proposed.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: testInfo.outputPath(`room-lead-fixture-proposal-${viewport.name}.png`),
        fullPage: false,
      });

      const linked = panel.getByRole("article", { name: "Linked task", exact: true });
      await linked.scrollIntoViewIfNeeded();
      await expect(linked.getByText("Waiting for review", { exact: true })).toBeVisible();
      await expect(linked.getByText("Next: you", { exact: true })).toBeVisible();
      await expect(
        linked.getByRole("link", { name: "Open task board", exact: true }),
      ).toBeVisible();
      await page.screenshot({
        path: testInfo.outputPath(`room-lead-fixture-task-${viewport.name}.png`),
        fullPage: false,
      });

      await panel.getByRole("button", { name: "Configure lead", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Configure lead", exact: true });
      await expect(dialog.getByRole("combobox", { name: "Lead agent", exact: true })).toHaveText(
        leadName,
      );
      await expect(dialog.getByRole("button", { name: "Save lead", exact: true })).toBeEnabled();
      await expect(dialog.getByRole("button", { name: "Save lead", exact: true })).toBeInViewport();
      await dialog.screenshot({
        path: testInfo.outputPath(`room-lead-fixture-policy-${viewport.name}.png`),
      });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      ).toBe(true);
      expect(unexpectedWrites).toEqual([]);
    } finally {
      const removed = await page.request.delete(`/api/conversations/${roomId}`);
      expect(removed.ok(), "remove only this owned visual-fixture room").toBe(true);
    }
  });
}
