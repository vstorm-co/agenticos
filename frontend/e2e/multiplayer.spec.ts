import type {
  APIRequestContext,
  APIResponse,
  BrowserContext,
  Page,
  Response,
} from "@playwright/test";
import type { RoomAgentRequest, RoomMessageCreate, RoomMessageResult } from "../src/types/room";

import { expect, test } from "./fixtures";
import {
  AUTH_STATE,
  COLLEAGUE_EMAIL,
  COLLEAGUE_PASSWORD,
  FAKE_KEY_LABEL,
  STUB_MODEL_ENDPOINT,
  json,
  nowListed,
  rowsAt,
  signInAs,
} from "./helpers";

test.use({ storageState: AUTH_STATE });

interface RoomFixture {
  agentId: string;
  agentName: string;
  queuedAgentId: string;
  queuedAgentName: string;
  profileId: string;
  projectId: string;
  orgId: string;
  orgName: string;
  colleagueId: string;
  echo: string;
}

let fixture: RoomFixture;
let owner: BrowserContext | undefined;
const cleanupPaths: string[] = [];

async function accepted<T>(response: APIResponse | Response, description: string): Promise<T> {
  expect(response.ok(), `${description}: ${response.status()} ${await response.text()}`).toBe(true);
  return (await response.json()) as T;
}

async function requestStatus(
  request: APIRequestContext,
  roomId: string,
  requestId: string,
  status: RoomAgentRequest["status"],
): Promise<RoomAgentRequest> {
  const path = `/api/conversations/${roomId}/room-requests`;
  let found: RoomAgentRequest | undefined;
  await expect
    .poll(
      async () => {
        const result = await json<{ items: RoomAgentRequest[] }>(request, path);
        found = result.items.find((item) => item.id === requestId);
        return found;
      },
      { timeout: 45_000, message: `room request ${requestId} never became ${status}` },
    )
    .toMatchObject({ status });
  return found!;
}

async function newRoom(page: Page): Promise<string> {
  await page.goto(`/projects/${fixture.projectId}?tab=chats`);
  await expect(page.getByRole("tab", { name: "Chats", exact: true })).toHaveAttribute(
    "data-state",
    "active",
  );
  const created = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/conversations" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "New team room", exact: true }).click();
  const room = await accepted<{ id: string; project_id: string }>(
    await created,
    "creating the empty team room",
  );
  cleanupPaths.push(`/api/conversations/${room.id}`);
  expect(room.project_id).toBe(fixture.projectId);
  await expect(page).toHaveURL(new RegExp(`/chat\\?id=${room.id}$`));
  await expect(page.getByRole("textbox", { name: "Message to the team" })).toBeEnabled();
  expect(await rowsAt(page.request, `/api/conversations/${room.id}/messages`)).toHaveLength(0);
  return room.id;
}

async function postMessage(page: Page, roomId: string, content: string) {
  await page.getByRole("textbox", { name: "Message to the team" }).fill(content);
  const received = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/conversations/${roomId}/room-messages` &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Post message", exact: true }).click();
  return accepted<RoomMessageResult>(await received, "posting to the room");
}

async function askAgent(page: Page, name = fixture.agentName): Promise<void> {
  await page.getByRole("combobox", { name: "Who should answer" }).click();
  await page.getByRole("option", { name: `Ask @${name}`, exact: true }).click();
}

async function colleaguePage(
  browser: Parameters<typeof signInAs>[0],
  failures: string[],
): Promise<Page> {
  const context = await signInAs(browser, COLLEAGUE_EMAIL, COLLEAGUE_PASSWORD);
  const page = await context.newPage();
  // The shared fixture watches the owner's page; a second participant needs the
  // same failure net, including calls made while switching organization.
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (response.status() >= 500 && path.startsWith("/api/") && !path.startsWith("/api/rag/")) {
      failures.push(`colleague: ${response.status()} ${response.request().method()} ${path}`);
    }
  });
  await page.route("**/api/releases/current", (route) =>
    route.fulfill({ json: { release: null } }),
  );
  await page.route("**/api/releases/latest", (route) => route.fulfill({ json: { latest: null } }));
  await page.goto("/chat");
  const organizations = await rowsAt(page.request, "/api/orgs");
  const organizationIndex = organizations.findIndex((row) => row.id === fixture.orgId);
  expect(organizationIndex, "the colleague lost the project organization").toBeGreaterThanOrEqual(
    0,
  );
  const switcher = page.locator('[data-tour="organization-switcher"]');
  await switcher.click();
  // Personal organizations can share a display name. The menu renders the
  // authenticated organization list in order; choose the verified ID's row.
  const organization = page.getByRole("menuitem").nth(organizationIndex);
  await expect(organization).toContainText(fixture.orgName);
  await organization.click();
  await expect(switcher).toContainText(fixture.orgName);
  return page;
}

async function shareProject(page: Page): Promise<void> {
  await page
    .locator('[data-tour="chat-team-room"]')
    .getByRole("button", { name: "Share", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("People with access", { exact: true })).toBeVisible();
  await dialog.getByLabel("Add a person or group").click();
  await page.getByRole("option", { name: COLLEAGUE_EMAIL }).click();
  await dialog.getByRole("button", { name: "Share", exact: true }).click();
  const level = dialog.getByLabel(`Access for ${COLLEAGUE_EMAIL}`);
  await expect(level).toHaveText("Can view");
  await level.click();
  await page.getByRole("option", { name: "Can use", exact: true }).click();
  await expect(level).toHaveText("Can use");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
}

async function assertOneSavedAnswer(page: Page, roomId: string, runId: string): Promise<string> {
  let answers: Record<string, unknown>[] = [];
  await expect
    .poll(async () => {
      answers = (await rowsAt(page.request, `/api/conversations/${roomId}/messages`)).filter(
        (row) => row.role === "assistant" && row.run_id === runId && row.content === fixture.echo,
      );
      return answers.length;
    })
    .toBe(1);
  const id = String(answers[0]!.id);
  await expect(page.locator(`[data-message-id="${id}"]`)).toHaveCount(1);
  await expect(page.locator(`[data-message-id="${id}"]`)).toContainText(fixture.echo);
  return id;
}

test.describe("multiplayer project rooms", () => {
  test.describe.configure({ mode: "serial", timeout: 180_000 });

  test.beforeAll(async ({ browser }) => {
    owner = await browser.newContext({ storageState: AUTH_STATE });
    const request = owner.request;
    const stamp = Date.now().toString(36);
    const org = (await rowsAt(request, "/api/orgs"))[0];
    expect(org, "bootstrap left no owner organization").toBeDefined();
    const colleague = (await rowsAt(request, `/api/orgs/${org!.id}/members`)).find(
      (row) => row.email === COLLEAGUE_EMAIL,
    );
    expect(colleague, "the seeded colleague is not an organization member").toBeDefined();
    const key = (await rowsAt(request, "/api/secrets")).find((row) => row.name === FAKE_KEY_LABEL);
    expect(key, `the seed did not store ${FAKE_KEY_LABEL}`).toBeDefined();

    // Unique, test-owned rows, as in artifact-live-data.spec.ts. The feature
    // under test is room submission, not the model/agent editor.
    const profile = await accepted<{ id: string }>(
      await request.post("/api/providers/model-profiles", {
        data: {
          label: `e2e-room-model-${stamp}`,
          provider: "openai",
          model: "gpt-4.1-mini",
          secret_id: key!.id,
          base_url: STUB_MODEL_ENDPOINT,
        },
      }),
      "creating the local stub profile",
    );
    cleanupPaths.push(`/api/providers/model-profiles/${profile.id}`);
    const agentName = `E2E Room ${stamp}`;
    const echo = `PONG-ROOM-${stamp}`;
    const agent = await accepted<{ id: string }>(
      await request.post("/api/agents", { data: { spec: { name: agentName } } }),
      "creating the room responder",
    );
    cleanupPaths.push(`/api/agents/${agent.id}`);
    const draft = await request.put(`/api/agents/${agent.id}/draft`, {
      data: {
        spec: {
          name: agentName,
          instructions: `Reply with exactly ${echo}. Follow a CALL-TOOL directive when one is present.`,
          model_profile_id: profile.id,
          capabilities: [{ id: "ask_user", enabled: true, config: {} }],
        },
      },
    });
    expect(draft.ok(), `saving the responder draft: ${draft.status()}`).toBe(true);
    const published = await request.post(`/api/agents/${agent.id}/publish`, { data: {} });
    expect(published.ok(), `publishing the responder: ${published.status()}`).toBe(true);
    await nowListed(request, "/api/agents", "id", agent.id);
    const granted = await request.put(`/api/agents/${agent.id}/sharing/grants`, {
      data: { subject_user_id: colleague!.user_id, level: "use" },
    });
    expect(granted.status()).toBe(200);
    // A second responder has no question tool. The saved earlier CALL-TOOL
    // prompt remains in history, so the shared model stub must not ask it again
    // while testing that another agent's queued request can follow the first.
    const queuedAgentName = `E2E Room Reply ${stamp}`;
    const queuedAgent = await accepted<{ id: string }>(
      await request.post("/api/agents", { data: { spec: { name: queuedAgentName } } }),
      "creating the plain queued responder",
    );
    cleanupPaths.push(`/api/agents/${queuedAgent.id}`);
    const queuedDraft = await request.put(`/api/agents/${queuedAgent.id}/draft`, {
      data: {
        spec: {
          name: queuedAgentName,
          instructions: `Reply with exactly ${echo}.`,
          model_profile_id: profile.id,
          capabilities: [],
        },
      },
    });
    expect(queuedDraft.ok()).toBe(true);
    const queuedPublished = await request.post(`/api/agents/${queuedAgent.id}/publish`, {
      data: {},
    });
    expect(queuedPublished.ok()).toBe(true);
    const queuedGrant = await request.put(`/api/agents/${queuedAgent.id}/sharing/grants`, {
      data: { subject_user_id: colleague!.user_id, level: "use" },
    });
    expect(queuedGrant.status()).toBe(200);
    await nowListed(request, "/api/agents", "id", queuedAgent.id);
    const project = await accepted<{ id: string }>(
      await request.post("/api/projects", { data: { name: `E2E Multiplayer ${stamp}` } }),
      "creating the isolated test project",
    );
    cleanupPaths.push(`/api/projects/${project.id}`);
    await nowListed(request, "/api/projects", "id", project.id);
    fixture = {
      agentId: agent.id,
      agentName,
      queuedAgentId: queuedAgent.id,
      queuedAgentName,
      profileId: profile.id,
      projectId: project.id,
      orgId: String(org!.id),
      orgName: String(org!.name),
      colleagueId: String(colleague!.user_id),
      echo,
    };
  });

  test.afterAll(async () => {
    const failures: string[] = [];
    try {
      if (owner) {
        // Record rows as soon as they are created, so failed setup is cleaned
        // too. One refusal must not prevent cleanup of the remaining rows.
        for (const path of cleanupPaths.toReversed()) {
          try {
            const removed = await owner.request.delete(path, { timeout: 10_000 });
            if (!removed.ok())
              failures.push(`${path}: ${removed.status()} ${await removed.text()}`);
          } catch (error) {
            failures.push(`${path}: ${String(error)}`);
          }
        }
      }
    } finally {
      await owner?.close();
    }
    expect(failures, "test-owned room fixtures were not removed").toEqual([]);
  });

  test("two members share human messages, retry one uncertain post, and recover one agent answer", async ({
    page,
    browser,
    apiFailures,
  }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.addInitScript(() => {
      window.__AGENTICOS_SHELL__ = {
        platform: "windows",
        window: "main",
        version: "0.2.0",
        vibrancy: false,
      };
    });
    const roomId = await newRoom(page);
    const workspace = await page.request.get(`/api/conversations/${roomId}/workspace`);
    expect(workspace.ok(), `reading the room workspace: ${workspace.status()}`).toBe(true);
    const files = page.getByRole("button", { name: /^Show the files/ });
    await files.click();
    const filePanel = page
      .getByRole("complementary")
      .filter({ has: page.getByRole("button", { name: "Close the file panel" }) });
    await expect(filePanel).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Message to the team" })).toBeInViewport();
    await filePanel.getByRole("button", { name: "Close the file panel" }).click();
    await expect(filePanel).toBeHidden();
    await expect(files).toBeFocused();
    await shareProject(page);
    const peer = await colleaguePage(browser, apiFailures);
    try {
      await peer.goto(`/chat?id=${roomId}`);
      await expect(peer.getByRole("textbox", { name: "Message to the team" })).toBeEnabled();
      await expect(page.locator('[data-tour="chat-team-room"]')).toContainText("Colleague is here");
      await expect(peer.locator('[data-tour="chat-team-room"]')).toContainText("Owner is here");
      await expect(page.getByRole("combobox", { name: "Who should answer" })).toHaveText(
        "Team only",
      );

      const note = await postMessage(page, roomId, `Owner update ${roomId}`);
      expect(note.request).toBeNull();
      const ownerRow = peer.locator(`[data-message-id="${note.message.id}"]`);
      await expect(ownerRow).toContainText(note.message.content);
      await ownerRow.hover();
      await ownerRow.getByRole("button", { name: "Reply", exact: true }).click();
      const reply = await postMessage(peer, roomId, `Colleague reply ${roomId}`);
      expect(reply.request).toBeNull();
      expect(reply.message).toMatchObject({
        sender: { user_id: fixture.colleagueId },
        reply_to: { message_id: note.message.id },
      });
      await expect(page.locator(`[data-message-id="${reply.message.id}"]`)).toContainText(
        reply.message.content,
      );
      expect(
        (
          await json<{ items: unknown[] }>(
            page.request,
            `/api/conversations/${roomId}/room-requests`,
          )
        ).items,
      ).toHaveLength(0);

      // The server commits the first POST, then only its acknowledgement is
      // lost. The retry must carry the same client ID and return the same row.
      let acceptedPost: RoomMessageResult | undefined;
      let submitted: RoomMessageCreate | undefined;
      const path = `/api/conversations/${roomId}/room-messages`;
      await page.route(
        `**${path}`,
        async (route) => {
          submitted = route.request().postDataJSON() as RoomMessageCreate;
          acceptedPost = await accepted<RoomMessageResult>(
            await route.fetch(),
            "the lost-ack post",
          );
          await route.abort("failed");
        },
        { times: 1 },
      );
      await page.getByRole("textbox", { name: "Message to the team" }).fill(`Retry once ${roomId}`);
      await page.getByRole("button", { name: "Post message", exact: true }).click();
      await expect(page.getByRole("button", { name: "Retry same message" })).toBeVisible();
      expect(acceptedPost).toBeDefined();
      const retryResponse = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === path && response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Retry same message" }).click();
      const retried = await retryResponse;
      expect(retried.request().postDataJSON()).toEqual(submitted);
      const retryResult = await accepted<RoomMessageResult>(retried, "retrying the same post");
      expect(retryResult.message.id).toBe(acceptedPost!.message.id);
      expect(
        (await rowsAt(page.request, `/api/conversations/${roomId}/messages`)).filter(
          (row) => row.client_message_id === submitted!.client_message_id,
        ),
      ).toHaveLength(1);
      await expect(peer.locator(`[data-message-id="${retryResult.message.id}"]`)).toHaveCount(1);

      await peer.context().setOffline(true);
      await askAgent(page);
      const asked = await postMessage(page, roomId, "Please acknowledge the team's updates.");
      expect(asked.request).not.toBeNull();
      const completed = await requestStatus(page.request, roomId, asked.request!.id, "completed");
      expect(completed.requester_id).toBe(note.message.sender!.user_id);
      const answerId = await assertOneSavedAnswer(page, roomId, completed.run_id!);
      await peer.context().setOffline(false);
      await expect(peer.locator(`[data-message-id="${answerId}"]`)).toContainText(fixture.echo);
      await page.reload();
      await peer.reload();
      await assertOneSavedAnswer(page, roomId, completed.run_id!);
      await expect(peer.locator(`[data-message-id="${answerId}"]`)).toHaveCount(1);
      await expect(peer.locator(`[data-message-id="${answerId}"]`)).toContainText(fixture.echo);
    } finally {
      await peer.context().setOffline(false);
      await peer.context().close();
    }
  });

  test("a parked question holds the queue, only its asker resumes it, and a teammate cancels their queued request", async ({
    page,
    browser,
    apiFailures,
  }) => {
    const roomId = await newRoom(page);
    const peer = await colleaguePage(browser, apiFailures);
    try {
      await peer.goto(`/chat?id=${roomId}`);
      await expect(peer.getByRole("textbox", { name: "Message to the team" })).toBeEnabled();
      const question = "Ready to continue the first room request?";
      const args = Buffer.from(
        JSON.stringify({
          questions: [
            {
              question,
              header: "Room order",
              options: [
                { label: "Continue the first request", description: "Let its saved run finish." },
                { label: "Decline", description: "Do not continue." },
              ],
              multi_select: false,
            },
          ],
        }),
      ).toString("base64url");
      await askAgent(page);
      const first = await postMessage(page, roomId, `CALL-TOOL:ask_user_question:${args}`);
      const parked = await requestStatus(
        page.request,
        roomId,
        first.request!.id,
        "awaiting_answer",
      );
      await expect(page.getByText(question, { exact: true })).toBeVisible();

      const questions = await json<{ tool_call_id: string }[]>(
        page.request,
        `/api/runs/${parked.run_id}/questions`,
      );
      expect(questions).toHaveLength(1);
      const refused = await peer.request.post(`/api/runs/${parked.run_id}/answers`, {
        headers: { "X-Organization-Id": fixture.orgId },
        data: {
          responses: {
            [questions[0]!.tool_call_id]: [
              { answer: "", selected: ["Continue the first request"], skipped: false },
            ],
          },
        },
      });
      expect(refused.status()).toBe(403);

      await askAgent(peer);
      const cancelled = await postMessage(peer, roomId, "This queued request will be cancelled.");
      await requestStatus(page.request, roomId, cancelled.request!.id, "queued");
      await expect(peer.getByRole("button", { name: "Cancel request", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Cancel request", exact: true })).toHaveCount(
        0,
      );
      await peer.getByRole("button", { name: "Cancel request", exact: true }).click();
      expect(
        await requestStatus(page.request, roomId, cancelled.request!.id, "cancelled"),
      ).toMatchObject({ run_id: null });

      await askAgent(peer, fixture.queuedAgentName);
      const later = await postMessage(peer, roomId, "Answer after the first request is complete.");
      expect(await requestStatus(page.request, roomId, later.request!.id, "queued")).toMatchObject({
        run_id: null,
        requester_id: fixture.colleagueId,
      });
      await page.reload();
      await expect(page.getByText(question, { exact: true })).toBeVisible();
      // Reload recovers the original requester's question even with a later
      // queued request. Answer through the real chat's continuation path.
      await page.getByRole("button", { name: /Continue the first request/ }).click();
      const doneFirst = await requestStatus(page.request, roomId, first.request!.id, "completed");
      const doneLater = await requestStatus(page.request, roomId, later.request!.id, "completed");
      expect(doneLater.run_id).not.toBe(doneFirst.run_id);
      await assertOneSavedAnswer(page, roomId, doneFirst.run_id!);
      const laterAnswer = await assertOneSavedAnswer(page, roomId, doneLater.run_id!);
      await peer.reload();
      await expect(peer.locator(`[data-message-id="${laterAnswer}"]`)).toContainText(fixture.echo);
      expect(
        await requestStatus(page.request, roomId, cancelled.request!.id, "cancelled"),
      ).toMatchObject({ run_id: null });
    } finally {
      await peer.context().close();
    }
  });
});
