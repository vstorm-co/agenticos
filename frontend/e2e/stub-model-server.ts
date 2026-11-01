import { createServer } from "node:http";

/**
 * An OpenAI-compatible model server, for the one spec that needs a model to
 * answer.
 *
 * `journey.spec.ts` is the only test that runs an agent end to end, and it used
 * to need a real provider key - so it skipped itself in every environment that
 * did not have one, which is every environment. A key that costs money and
 * answers differently every time is a poor fixture anyway: the journey is about
 * the platform's seams, not about whether OpenAI is up.
 *
 * So this serves the Chat Completions API, which is what a profile built as
 * `openai-chat` speaks, and what every OpenAI-compatible server in the world
 * speaks - vLLM, LM Studio, a LiteLLM proxy. Pointing a profile's endpoint at it
 * exercises the same resolver, the same client and the same streaming path a
 * real provider would, minus the network and the bill. It is reached over
 * loopback, which model profiles allow deliberately: a local model is a
 * first-class provider here, not an SSRF attempt.
 *
 * What it deliberately does *not* do:
 *
 * - **Authenticate.** The journey stores a key and binds the model to it,
 *   because that binding is what spend is attributed to. Whether the key is
 *   accepted is the provider's business, and asserting on it here would be
 *   asserting on this file.
 * - **Call tools on its own initiative.** It answers in one turn unless the
 *   request asks for a delegation, which `delegation.spec.ts` needs - see
 *   `DELEGATE` - or names a tool call outright, which
 *   `artifact-live-data.spec.ts` needs - see `CALL_TOOL`. A stub that decided by
 *   itself which tools to call would be a stub that decides what the agent does,
 *   and the tool paths have their own specs.
 * - **Generate text.** It echoes the token it was told to say, which is the
 *   point: the only way that token reaches the reply is if the published
 *   agent's instructions reached the model request. That seam - spec to
 *   provider - is exactly what a fake key could never prove.
 */

/** Deliberately not 3000 or 8000: the frontend and the API own those. */
const PORT = Number(process.env.E2E_STUB_MODEL_PORT ?? 4010);

/**
 * Where it listens. Loopback unless told otherwise: an API in a container cannot
 * reach the host's `127.0.0.1`, so a run against one binds `0.0.0.0` and names
 * the host's address in the model profile instead.
 */
const BIND = process.env.E2E_STUB_MODEL_BIND ?? "127.0.0.1";

/**
 * What the caller asked to be said back.
 *
 * The journey writes "Reply with exactly PONG-<stamp>" into the agent's
 * instructions, so finding it in the request is the same fact as the
 * instructions having been sent. Absent it, this answers something plainly
 * recognisable rather than inventing prose.
 */
const ECHO = /\bPONG-[A-Za-z0-9-]+\b/;

const FALLBACK = "The stub model answered.";

/**
 * The delegate a caller's instructions name, when they name one.
 *
 * `ECHO`'s sibling, and it exists for the same reason. Delegation is the one
 * behaviour in this product that a model has to *start*: nothing the platform
 * does puts a specialist to work until a model calls `task`, so a stub that only
 * ever answers in prose leaves the whole feature unreachable from an end-to-end
 * test. Handing the decision back to the request keeps this file from making it:
 * the directive can only arrive through a published agent's instructions, and the
 * tool can only be on the request if the capability was bound and a delegate
 * resolved. `delegation.spec.ts` then asserts on the *delegate's* own answer,
 * which nothing here could produce.
 */
const DELEGATE = /\bDELEGATE-TO:([a-z0-9][a-z0-9-]*)\b/;

/**
 * The delegation tool, under the id `app/agents/capabilities/subagents` declares.
 *
 * A binding may rename it for its own model. None does in this suite, and a spec
 * that renamed it would have to say so here too - which is the right amount of
 * friction for a fixture that would otherwise silently stop delegating.
 */
const TASK_TOOL = "task";

/**
 * What the delegation is asked to do.
 *
 * Deliberately carries no `ECHO` token: it becomes the delegate's prompt, and a
 * token planted here would be answered by the *parent's* instruction reaching the
 * delegate rather than by the delegate's own - which is precisely the seam the
 * spec is checking.
 */
const DELEGATED_TASK = "Say your line.";

/**
 * A tool call the request spells out in full: `CALL-TOOL:<tool>:<arguments>`,
 * the arguments as base64url JSON.
 *
 * `DELEGATE`'s sibling, for a tool whose arguments are the spec's to choose - a
 * page and the views it binds, which only the spec knows the ids of. The stub
 * decides nothing: it decodes what it was given and calls the tool it was named,
 * under the same two guards as a delegation (`toolCallFor`). base64url because
 * the arguments are JSON holding HTML, and a prompt that carried them raw would
 * be one quote away from a directive this pattern no longer matches.
 */
const CALL_TOOL = /\bCALL-TOOL:([A-Za-z0-9_]+):([A-Za-z0-9_-]+)/;

/** One tool call this stub answers with: the tool, and its arguments as JSON text. */
interface ToolCall {
  name: string;
  arguments: string;
}

interface ChatMessage {
  role?: string;
  content?: unknown;
}

/** As much of a tool declaration as deciding whether to call one needs. */
interface ChatTool {
  function?: { name?: string; parameters?: { properties?: Record<string, unknown> } };
}

interface ChatRequest {
  model?: string;
  messages?: ChatMessage[];
  tools?: ChatTool[];
  stream?: boolean;
}

/**
 * Every scrap of text in the request, flattened.
 *
 * Content is a string on a plain message and a list of parts on a multimodal
 * one, and instructions arrive as a system message in either shape - so this
 * walks whatever it is given rather than assuming the easy case.
 */
function allText(body: ChatRequest): string {
  const parts: string[] = [];
  const walk = (value: unknown): void => {
    if (typeof value === "string") parts.push(value);
    else if (Array.isArray(value)) value.forEach(walk);
    else if (value !== null && typeof value === "object") Object.values(value).forEach(walk);
  };
  walk(body.messages ?? []);
  return parts.join(" ");
}

/** How `system_agent_runner.output_contract` closes a system agent's prompt; the schema follows. */
const OUTPUT_CONTRACT = "It must validate against this JSON schema:\n";

/** The top-level properties of the answer a system agent was asked for, or `null`. */
function contractProperties(body: ChatRequest): Record<string, object> | null {
  const prompt = allText(body);
  const at = prompt.lastIndexOf(OUTPUT_CONTRACT);
  if (at < 0) return null;
  // The contract closes the prompt, so the schema is what follows it up to its last brace.
  const tail = prompt.slice(at + OUTPUT_CONTRACT.length);
  try {
    const schema: { properties?: Record<string, object> } = JSON.parse(
      tail.slice(0, tail.lastIndexOf("}") + 1),
    );
    return schema.properties ?? null;
  } catch {
    return null;
  }
}

/** The marker `improvement.mobile.spec.ts` writes in its note to the helper; it is answered differently. */
const TRY_AGAIN_NOTE = "E2E-NOTE";

/** Fixed JSON answers only for the improvement journey's explicit fixture marker.
 * The real API, worker, evidence builder and eval scorer still do all their work.
 */
function improvementReply(body: ChatRequest): string | null {
  if (!allText(body).includes("E2E-IMPROVEMENT")) return null;
  const properties = contractProperties(body);
  if (properties === null) return null;
  if ("summary" in properties && "expected_effect" in properties && "instructions" in properties) {
    // Two changes, so one can be left out of a test; a person's note to the helper
    // words the second apart, so the attempt it asks for is no repeat of the last.
    const noted = allText(body).includes(TRY_AGAIN_NOTE);
    return JSON.stringify({
      summary: "The fixture answers with the old return policy.",
      expected_effect: "Use the reviewed policy token for the test questions.",
      instructions: [
        {
          old_text: "PONG-IMPROVEMENT-BEFORE",
          new_text: "PONG-IMPROVEMENT-AFTER",
          after: "",
          rationale: "The deterministic checks expect the reviewed policy.",
          evidence: [],
        },
        {
          old_text: "and nothing else.",
          new_text: noted
            ? "and nothing else, as the note asks."
            : "and nothing else, in one line.",
          after: "",
          rationale: "An answer of the token alone is what the checks compare.",
          evidence: [],
        },
      ],
      tools: [],
      fields: [],
      new_skills: [],
    });
  }
  if ("findings" in properties) return JSON.stringify({ findings: [] });
  return null;
}

function replyFor(body: ChatRequest): string {
  return ECHO.exec(allText(body))?.[0] ?? FALLBACK;
}

/**
 * The delegate this request should be answered with a call to, or `null`.
 *
 * Three conditions, and each of them is a fact about the deployment rather than
 * about this file:
 *
 * - the instructions name a delegate, so the published spec reached the provider;
 * - the request offers `task`, so the capability was bound and a delegate
 *   resolved - without this a deployment where delegation was never wired up
 *   would answer a call to a tool it does not have, turning a missing feature
 *   into a model error two layers away from the cause;
 * - nothing has come back from a tool yet. The second request of a delegating
 *   turn carries the result, and answering it with the same call again is an
 *   infinite loop rather than a fixture. It is also what makes the *delegate's*
 *   own request safe: it is sent with no delegation tool at all, so a delegate
 *   never delegates however its prompt reads.
 */
function delegateFor(body: ChatRequest): string | null {
  if (toolAnswered(body)) return null;
  const named = DELEGATE.exec(allText(body))?.[1];
  if (named === undefined) return null;
  return offers(body, TASK_TOOL) ? named : null;
}

/** A tool has answered in this turn, so the next reply is prose and nothing loops. */
function toolAnswered(body: ChatRequest): boolean {
  return (body.messages ?? []).some((message) => message.role === "tool");
}

/** The request offers this tool, so the capability behind it was bound. */
function offers(body: ChatRequest, name: string): boolean {
  return (body.tools ?? []).some((tool) => tool.function?.name === name);
}

/**
 * The tool call a `CALL-TOOL` directive asks for, or `null`.
 *
 * The same two guards as `delegateFor`, for the same reasons: the named tool has
 * to be on the request, so a capability that was never bound fails as a missing
 * tool call rather than a model calling a tool it does not have; and no tool has
 * answered yet, so the second request of the turn - which carries the result - is
 * answered in prose. Arguments that do not decode to a JSON object are not a
 * directive: the stub calls nothing rather than invent arguments.
 */
function toolCallFor(body: ChatRequest): ToolCall | null {
  if (toolAnswered(body)) return null;
  const match = CALL_TOOL.exec(allText(body));
  if (match === null) return null;
  const [, name = "", encoded = ""] = match;
  if (!offers(body, name)) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
  return { name, arguments: JSON.stringify(parsed) };
}

/**
 * Token counts that are wrong but not absurd, and above all *stable*.
 *
 * The journey asserts the run carries a cost, which is computed from these by
 * the bundled price list - so returning zero usage would make the spec pass on
 * a run that metered nothing, which is the one thing it is there to catch.
 */
function usageFor(prompt: string, answer: string): Record<string, number> {
  const prompt_tokens = Math.max(1, Math.ceil(prompt.length / 4));
  const completion_tokens = Math.max(1, Math.ceil(answer.length / 4));
  return { prompt_tokens, completion_tokens, total_tokens: prompt_tokens + completion_tokens };
}

/** Fixed, because a chunk id that moved would be the only unstable thing here. */
const COMPLETION_ID = "chatcmpl-e2e-stub";
const CREATED = 1_700_000_000;
/** One tool call per turn, so one id is enough and a fixed one reads plainly. */
const TOOL_CALL_ID = "call-e2e-task";

function completion(model: string, answer: string, usage: Record<string, number>): string {
  return JSON.stringify({
    id: COMPLETION_ID,
    object: "chat.completion",
    created: CREATED,
    model,
    choices: [
      {
        index: 0,
        message: { role: "assistant", content: answer },
        finish_reason: "stop",
      },
    ],
    usage,
  });
}

/**
 * A delegation, as a call to `task` with the arguments the library's own tool
 * signature names.
 *
 * `mode` is deliberately not sent. The platform replaces it on the way through
 * with the one the agent's author configured, and a stub that named a mode would
 * hide the turn where that replacement stopped happening.
 */
function delegationCall(subagent: string): ToolCall {
  return {
    name: TASK_TOOL,
    arguments: JSON.stringify({ subagent_type: subagent, description: DELEGATED_TASK }),
  };
}

/** A turn that calls a tool instead of answering. */
function toolCallCompletion(model: string, call: ToolCall, usage: Record<string, number>): string {
  return JSON.stringify({
    id: COMPLETION_ID,
    object: "chat.completion",
    created: CREATED,
    model,
    choices: [
      {
        index: 0,
        message: {
          role: "assistant",
          content: null,
          tool_calls: [
            {
              id: TOOL_CALL_ID,
              type: "function",
              function: { name: call.name, arguments: call.arguments },
            },
          ],
        },
        finish_reason: "tool_calls",
      },
    ],
    usage,
  });
}

/** One `chat.completion.chunk`, as an SSE frame. */
function chunk(model: string, choices: unknown[], extra: Record<string, unknown> = {}): string {
  return `data: ${JSON.stringify({
    id: COMPLETION_ID,
    object: "chat.completion.chunk",
    created: CREATED,
    model,
    choices,
    ...extra,
  })}\n\n`;
}

/**
 * The same answer as Server-Sent Events, which is the path the chat takes.
 *
 * The websocket streams deltas to the browser, so the run opens a streaming
 * request - a stub that only answered in one JSON body would leave the whole
 * streaming path unexercised and the chat waiting. The final chunk carries the
 * usage, as `stream_options.include_usage` asks for; it is sent unconditionally
 * because a run with no usage is a run with no cost.
 */
function* streamChunks(model: string, answer: string, usage: Record<string, number>) {
  yield chunk(model, [
    { index: 0, delta: { role: "assistant", content: "" }, finish_reason: null },
  ]);
  yield chunk(model, [{ index: 0, delta: { content: answer }, finish_reason: null }]);
  yield chunk(model, [{ index: 0, delta: {}, finish_reason: "stop" }]);
  yield chunk(model, [], { usage });
  yield "data: [DONE]\n\n";
}

/**
 * The tool-calling turn, streamed.
 *
 * The arguments arrive in a chunk of their own after the one that names the tool,
 * which is how a provider sends them and therefore the shape worth exercising: an
 * SDK that only assembled a tool call from a single frame would pass a
 * one-chunk stub and fail against OpenAI.
 */
function* toolCallChunks(model: string, call: ToolCall, usage: Record<string, number>) {
  yield chunk(model, [
    {
      index: 0,
      delta: {
        role: "assistant",
        tool_calls: [
          {
            index: 0,
            id: TOOL_CALL_ID,
            type: "function",
            function: { name: call.name, arguments: "" },
          },
        ],
      },
      finish_reason: null,
    },
  ]);
  yield chunk(model, [
    {
      index: 0,
      delta: { tool_calls: [{ index: 0, function: { arguments: call.arguments } }] },
      finish_reason: null,
    },
  ]);
  yield chunk(model, [{ index: 0, delta: {}, finish_reason: "tool_calls" }]);
  yield chunk(model, [], { usage });
  yield "data: [DONE]\n\n";
}

const server = createServer((request, response) => {
  const path = (request.url ?? "").split("?")[0] ?? "";

  if (request.method === "GET" && path === "/health") {
    response.writeHead(200, { "content-type": "text/plain" }).end("ok");
    return;
  }

  // Asked by nothing in the journey - the model id is typed in - but a server
  // that 404s its own catalog is a confusing thing to point a deployment at.
  if (request.method === "GET" && path.endsWith("/models")) {
    response
      .writeHead(200, { "content-type": "application/json" })
      .end(JSON.stringify({ object: "list", data: [{ id: "gpt-4.1-mini", object: "model" }] }));
    return;
  }

  if (request.method !== "POST" || !path.endsWith("/chat/completions")) {
    response
      .writeHead(404, { "content-type": "application/json" })
      .end(JSON.stringify({ error: { message: `no route for ${request.method} ${path}` } }));
    return;
  }

  const chunks: Buffer[] = [];
  request.on("data", (chunk: Buffer) => chunks.push(chunk));
  request.on("end", () => {
    let body: ChatRequest;
    try {
      body = JSON.parse(Buffer.concat(chunks).toString("utf8")) as ChatRequest;
    } catch {
      // The shape the SDK raises on, rather than a bare 400: a malformed body is
      // this stub's bug and should read as one.
      response
        .writeHead(400, { "content-type": "application/json" })
        .end(JSON.stringify({ error: { message: "the stub model could not parse the request" } }));
      return;
    }

    const model = body.model ?? "gpt-4.1-mini";
    const subagent = delegateFor(body);
    const call = subagent === null ? toolCallFor(body) : delegationCall(subagent);
    // Empty on a tool-calling turn, which is what a provider sends beside a tool
    // call: the agent has not said anything yet, and inventing prose for it
    // would put words in the transcript the agent never generated.
    const answer = call === null ? (improvementReply(body) ?? replyFor(body)) : "";
    const usage = usageFor(allText(body), answer);

    if (body.stream === true) {
      response.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "keep-alive",
      });
      const frames =
        call === null ? streamChunks(model, answer, usage) : toolCallChunks(model, call, usage);
      for (const frame of frames) response.write(frame);
      response.end();
      return;
    }

    response
      .writeHead(200, { "content-type": "application/json" })
      .end(
        call === null ? completion(model, answer, usage) : toolCallCompletion(model, call, usage),
      );
  });
});

server.listen(PORT, BIND, () => {
  // Playwright waits on /health rather than on this line, but a server that
  // says nothing is one nobody can tell apart from a port already taken.
  console.log(`stub model server listening on http://${BIND}:${PORT}`);
});
