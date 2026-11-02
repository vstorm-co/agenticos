import type { APIRequestContext, Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { AUTH_STATE } from "./helpers";

test.use({ storageState: AUTH_STATE, actionTimeout: 60_000 });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function record(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Error("Expected an API object");
  return value;
}
function id(value: Record<string, unknown>): string {
  if (typeof value.id !== "string") throw new Error("Expected a persisted resource identity");
  return value.id;
}
async function read(api: APIRequestContext, path: string, headers: Record<string, string>) {
  const response = await api.get(`/api${path}`, { headers });
  expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  return record(await response.json());
}
async function write(
  api: APIRequestContext,
  method: "post" | "put" | "patch",
  path: string,
  headers: Record<string, string>,
  data: object,
) {
  const response = await api[method](`/api${path}`, { headers, data });
  expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  return record(await response.json());
}

/**
 * The tokens the stub answers with, by the line of the served skill an agent's
 * role and a question's topic select (`skillReply` in `stub-model-server.ts`).
 */
const TOKEN = {
  credit: "PONG-SL-CREDIT",
  refund: "PONG-SL-REFUND",
  no: "PONG-SL-NO",
  noAfterDownload: "PONG-SL-NO-AFTER-DOWNLOAD",
} as const;

type Role = "online" | "counter" | "wholesale";
type Topic = "receipt" | "digital";

/** The Skills lab's rule 2 (receipts) and rule 3 (digital goods), one line per role. */
function skillBody(lines: Record<Role, Record<Topic, string>>): string {
  return (Object.keys(lines) as Role[])
    .flatMap((role) =>
      (Object.keys(lines[role]) as Topic[]).map(
        (topic) => `${role}/${topic}: ${lines[role][topic]}`,
      ),
    )
    .join("\n");
}

const V1 = {
  online: { receipt: TOKEN.credit, digital: TOKEN.no },
  counter: { receipt: TOKEN.credit, digital: TOKEN.no },
  wholesale: { receipt: TOKEN.credit, digital: TOKEN.no },
};

/** What each agent's test questions expect: A learns from the skill, B and C already pass. */
const EXPECTED: Record<Role, Record<Topic, string>> = {
  online: { receipt: TOKEN.refund, digital: TOKEN.noAfterDownload },
  counter: { receipt: TOKEN.credit, digital: TOKEN.no },
  wholesale: { receipt: TOKEN.refund, digital: TOKEN.no },
};

/** Instructions that open the skill and say nothing of its rules. */
function instructions(role: Role, skillName: string): string {
  const load = Buffer.from(JSON.stringify({ id: skillName }), "utf8").toString("base64url");
  return `E2E-SKILL-AS:${role} CALL-TOOL:load_capability:${load}`;
}

async function organizationHeaders(page: Page) {
  await page.goto("/agents");
  const activeOrganization = () =>
    page.evaluate(() => {
      const value: unknown = JSON.parse(localStorage.getItem("org-storage") ?? "null");
      if (typeof value !== "object" || value === null || !("state" in value)) return null;
      const state = value.state;
      return typeof state === "object" &&
        state !== null &&
        "activeOrgId" in state &&
        typeof state.activeOrgId === "string"
        ? state.activeOrgId
        : null;
    });
  await expect.poll(activeOrganization).toBeTruthy();
  const organizationId = (await activeOrganization()) ?? "";
  const headers = { "X-Organization-Id": organizationId };
  // The request context sends the browser's cookies but never refreshes them; an
  // access token that expired since sign-in is renewed by the page's own load.
  await expect
    .poll(async () => (await page.request.get(`/api/orgs/${organizationId}`, { headers })).status())
    .toBe(200);
  return { organizationId, headers };
}

/**
 * The Skills lab's shape on the stub model: one skill on main for A (Online
 * returns desk) and B (Gift shop counter), a fork of it for C (Wholesale desk),
 * each agent with checked test questions, measured once, and an improver.
 * Unique names keep the journey independent of other writers.
 */
async function seedSkillsLab(page: Page) {
  const { organizationId, headers } = await organizationHeaders(page);
  const api = page.request;
  const stamp = Date.now().toString(36);
  await write(api, "patch", `/orgs/${organizationId}`, headers, { ai_assistance_enabled: true });
  const secret = await write(api, "post", "/secrets", headers, {
    name: `skills-lab-${stamp}`,
    purpose: "openai",
    value: { kind: "api_key", api_key: "sk-e2e-stub-not-a-real-key" },
  });
  const model = await write(api, "post", "/providers/model-profiles", headers, {
    label: `Skills lab model ${stamp}`,
    provider: "openai",
    model: "gpt-4.1-mini",
    secret_id: id(secret),
    base_url: `http://127.0.0.1:${process.env.E2E_STUB_MODEL_PORT ?? 4010}/v1`,
    api: "chat",
  });
  await write(api, "post", "/agents/system", headers, {
    kind: "improver",
    name: `E2E Skill improver ${stamp}`,
    model_profile_id: id(model),
  });
  const skillName = `returns-policy-${stamp}`;
  const skill = await write(api, "post", "/skills", headers, {
    name: skillName,
    description:
      "E2E-SKILL. Acme's rules for returns and refunds. Open it for any return question.",
    content: skillBody(V1),
  });
  const v1 = String(skill.latest_version_id);
  const fork = await write(api, "post", `/skills/${id(skill)}/forks`, headers, {
    name: "Wholesale",
    from_version_id: v1,
  });
  await write(api, "post", `/skills/${id(skill)}/versions`, headers, {
    fork_id: id(fork),
    base_version_id: v1,
    description: String(skill.description),
    content: skillBody({ ...V1, wholesale: { ...V1.wholesale, receipt: TOKEN.refund } }),
  });

  async function agent(name: string, role: Role, binding?: { fork_id: string }) {
    const created = await write(api, "post", "/agents", headers, {
      spec: {
        name: `${name} ${stamp}`,
        instructions: instructions(role, skillName),
        model_profile_id: id(model),
        capabilities: [{ id: "skills" }],
        skill_ids: [id(skill)],
        ...(binding ? { skill_bindings: [{ skill_id: id(skill), ...binding }] } : {}),
      },
    });
    await write(api, "post", `/agents/${id(created)}/publish`, headers, {});
    const dataset = await write(api, "post", "/datasets", headers, {
      name: `${name} test questions ${stamp}`,
    });
    await write(api, "put", `/datasets/${id(dataset)}/scoring`, headers, {
      checks: { enabled: true, required: true },
      trajectory: { enabled: false },
      judge: { enabled: false },
      reference: { enabled: false },
      review: { select: "all" },
    });
    // Ten per topic: each attempt keeps half aside and a result needs five.
    for (const topic of ["receipt", "digital"] as const) {
      for (let n = 0; n < 10; n++) {
        await write(api, "post", `/datasets/${id(dataset)}/cases`, headers, {
          input: `TOPIC:${topic} Returns question ${n + 1}`,
          checks: [{ type: "equals", value: EXPECTED[role][topic] }],
        });
      }
    }
    const measured = await write(api, "post", `/agents/${id(created)}/eval-runs`, headers, {
      dataset_id: id(dataset),
      reruns: 0,
    });
    await expect
      .poll(async () => (await read(api, `/eval-runs/${id(measured)}`, headers)).status, {
        timeout: 90_000,
      })
      .toBe("completed");
    return { agent: created, dataset, measured };
  }

  const online = await agent("Online returns desk", "online");
  const counter = await agent("Gift shop counter", "counter");
  const wholesale = await agent("Wholesale desk", "wholesale", { fork_id: id(fork) });
  return { api, headers, stamp, skill, fork, online, counter, wholesale };
}

/**
 * Waits until a skill session stops where a person decides - `waiting`, with
 * what its Next step starts - or reaches `status` at its result.
 */
async function until(
  api: APIRequestContext,
  headers: Record<string, string>,
  path: string,
  status: "waiting" | "ready",
  nextStep?: "propose" | "check",
) {
  await expect
    .poll(
      async () => {
        const session = await read(api, path, headers);
        const there = session.status === status && (!nextStep || session.next_step === nextStep);
        return there ? "there" : `${String(session.status)} at ${String(session.stage)}`;
      },
      { timeout: 240_000 },
    )
    .toBe("there");
}

/** The priced Next step a person takes at a stop, with the consent agent Improve takes. */
async function nextStep(api: APIRequestContext, headers: Record<string, string>, path: string) {
  const session = await read(api, path, headers);
  const quote = await write(api, "post", `${path}/continue/estimate`, headers, {
    budget_usd: session.budget_usd,
  });
  await write(api, "post", `${path}/continue`, headers, {
    confirmed: true,
    budget_usd: quote.budget_usd,
    estimate_usd: quote.total_usd,
    candidate_hash: quote.candidate_hash,
  });
}

/** A session on the main line, from its start to the checked result. */
async function improveMain(
  api: APIRequestContext,
  headers: Record<string, string>,
  skillId: string,
) {
  const quote = await write(api, "post", `/skills/${skillId}/improvements/estimate`, headers, {
    fork_id: null,
  });
  expect(quote.affordable ?? true).toBeTruthy();
  const session = await write(api, "post", `/skills/${skillId}/improvements`, headers, {
    fork_id: null,
    budget_usd: "5",
  });
  const path = `/skills/${skillId}/improvements/${id(session)}`;
  await until(api, headers, path, "waiting", "propose");
  await nextStep(api, headers, path);
  await until(api, headers, path, "waiting", "check");
  await nextStep(api, headers, path);
  await until(api, headers, path, "ready");
  return { path, session: await read(api, path, headers) };
}

/** Each checked agent's state in a session's current check, by agent id. */
function checkedStates(session: Record<string, unknown>): Record<string, unknown> {
  const check = record(session.check);
  const agents = Array.isArray(check.agents) ? check.agents.map(record) : [];
  return Object.fromEntries(agents.map((row) => [id(record(row.agent)), row.state]));
}

/** The binding the skill's agents table reports for one agent. */
async function bindingOf(
  api: APIRequestContext,
  headers: Record<string, string>,
  skillId: string,
  agentId: string,
) {
  const list = await read(api, `/skills/${skillId}/agents`, headers);
  const rows = Array.isArray(list.items) ? list.items.map(record) : [];
  const row = rows.find((item) => record(item.agent).id === agentId);
  return row ? record(row.binding) : null;
}

/**
 * One skill, several agents: a change one agent fails is applied with that
 * agent pinned, a change that helps passes, and a fork catches up with main.
 * Actual API, worker, checks and persisted rows; only the model is a fixture.
 */
test("a shared skill improves on main, pins the agent it breaks and catches a fork up", async ({
  page,
}) => {
  test.fixme(true, "Waits for the skill session, its wizard and catching up");
  test.setTimeout(900_000);
  const { api, headers, skill, fork, online, counter, wholesale } = await seedSkillsLab(page);
  const skillId = id(skill);

  await test.step("the skill page lists each agent on its line", async () => {
    await page.goto(`/skills/${skillId}`);
    expect(await bindingOf(api, headers, skillId, id(online.agent))).toMatchObject({
      state: "main",
      version: { number: 1 },
    });
    expect(await bindingOf(api, headers, skillId, id(counter.agent))).toMatchObject({
      state: "main",
    });
    expect(await bindingOf(api, headers, skillId, id(wholesale.agent))).toMatchObject({
      state: "fork",
      fork: { id: id(fork), name: "Wholesale", base_number: 1, changes: 1 },
    });
  });

  await test.step("a change B fails is applied to main with B pinned", async () => {
    // Every `*/receipt` line to REFUND: A learns it, the gift shop counter must not.
    const { path, session } = await improveMain(api, headers, skillId);
    expect(checkedStates(session)).toMatchObject({
      [id(online.agent)]: "better",
      [id(counter.agent)]: "worse",
    });
    expect(record(session.check).verdict).toBe("blocked");
    expect(session.outcomes).toEqual(expect.arrayContaining(["apply_and_pin", "fork_for_helped"]));
    const applied = await write(api, "post", `${path}/apply`, headers, {
      confirmed: true,
      acknowledge_unknown: false,
      pin_worse: true,
    });
    expect(record(applied.version).number).toBe(2);
    expect(await bindingOf(api, headers, skillId, id(counter.agent))).toMatchObject({
      state: "pinned",
      version: { number: 1 },
      behind_main: 1,
    });
    expect(await bindingOf(api, headers, skillId, id(online.agent))).toMatchObject({
      state: "main",
      version: { number: 2 },
    });
  });

  await test.step("a change that helps and breaks nothing passes", async () => {
    // `online/digital` only. B is pinned, so the check does not run it.
    const { path, session } = await improveMain(api, headers, skillId);
    expect(checkedStates(session)).toEqual({ [id(online.agent)]: "better" });
    expect(record(session.check).verdict).toBe("passed");
    await write(api, "post", `${path}/apply`, headers, {
      confirmed: true,
      acknowledge_unknown: false,
      pin_worse: false,
    });
    expect(await bindingOf(api, headers, skillId, id(online.agent))).toMatchObject({
      state: "main",
      version: { number: 3 },
    });
    expect(await bindingOf(api, headers, skillId, id(counter.agent))).toMatchObject({
      state: "pinned",
      behind_main: 2,
    });
  });

  await test.step("the fork catches up with main", async () => {
    const behind = await read(api, "/skills/behind-main", headers);
    const lagging = (Array.isArray(behind.items) ? behind.items.map(record) : []).filter(
      (item) => record(item.skill).id === skillId,
    );
    expect(lagging.map((item) => [item.kind, item.behind_main])).toEqual(
      expect.arrayContaining([
        ["pinned", 2],
        ["fork", 2],
      ]),
    );
    const session = await write(
      api,
      "post",
      `/skills/${skillId}/forks/${id(fork)}/catch-up`,
      headers,
      {},
    );
    const path = `/skills/${skillId}/improvements/${id(session)}`;
    // Main changed its receipt lines and the online line, the fork only its
    // wholesale line, so every part merges by itself and nothing is proposed.
    await until(api, headers, path, "waiting", "check");
    const merge = await read(api, `/skills/${skillId}/merges/${String(session.merge_id)}`, headers);
    expect(merge.unresolved).toBe(0);
    await nextStep(api, headers, path);
    await until(api, headers, path, "ready");
    const result = await read(api, path, headers);
    // Main alone gives the wholesale desk store credit on receipts, so the fork stays.
    expect(result.outcomes).toContain("catch_up");
    expect(result.outcomes).not.toContain("return_to_main");
    await write(api, "post", `${path}/apply`, headers, {
      confirmed: true,
      acknowledge_unknown: false,
      outcome: "catch_up",
    });
    const forks = await read(api, `/skills/${skillId}/forks`, headers);
    const caughtUp = (Array.isArray(forks.items) ? forks.items.map(record) : []).find(
      (item) => item.id === id(fork),
    );
    expect(caughtUp).toMatchObject({ behind_main: 0, base: { number: 3 } });
    expect(await bindingOf(api, headers, skillId, id(wholesale.agent))).toMatchObject({
      state: "fork",
    });
  });
});
