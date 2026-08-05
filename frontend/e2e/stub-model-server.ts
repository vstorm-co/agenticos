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
 *   instructions it was sent ask for a delegation, which `delegation.spec.ts`
 *   needs and no other spec asks for - see `DELEGATE`. A stub that decided by
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

interface ChatMessage {
  role?: string;
  content?: unknown;
}

/** As much of a tool declaration as deciding whether to call one needs. */
interface ChatTool {
  function?: { name?: string };
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
  if ((body.messages ?? []).some((message) => message.role === "tool")) return null;
  const named = DELEGATE.exec(allText(body))?.[1];
  if (named === undefined) return null;
  return (body.tools ?? []).some((tool) => tool.function?.name === TASK_TOOL) ? named : null;
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
/** One delegation per turn, so one id is enough and a fixed one reads plainly. */
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

/** The `task` arguments, as the library's own tool signature names them. */
function taskArguments(subagent: string): string {
  return JSON.stringify({ subagent_type: subagent, description: DELEGATED_TASK });
}

/**
 * A turn that delegates instead of answering.
 *
 * `mode` is deliberately not sent. The platform replaces it on the way through
 * with the one the agent's author configured, and a stub that named a mode would
 * hide the turn where that replacement stopped happening.
 */
function delegation(model: string, subagent: string, usage: Record<string, number>): string {
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
              function: { name: TASK_TOOL, arguments: taskArguments(subagent) },
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
 * The delegating turn, streamed.
 *
 * The arguments arrive in a chunk of their own after the one that names the tool,
 * which is how a provider sends them and therefore the shape worth exercising: an
 * SDK that only assembled a tool call from a single frame would pass a
 * one-chunk stub and fail against OpenAI.
 */
function* delegationChunks(model: string, subagent: string, usage: Record<string, number>) {
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
            function: { name: TASK_TOOL, arguments: "" },
          },
        ],
      },
      finish_reason: null,
    },
  ]);
  yield chunk(model, [
    {
      index: 0,
      delta: { tool_calls: [{ index: 0, function: { arguments: taskArguments(subagent) } }] },
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
    // Empty on a delegating turn, which is what a provider sends beside a tool
    // call: the parent has not said anything yet, and inventing prose for it
    // would put words in the transcript the agent never generated.
    const answer = subagent === null ? replyFor(body) : "";
    const usage = usageFor(allText(body), answer);

    if (body.stream === true) {
      response.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "keep-alive",
      });
      const frames =
        subagent === null
          ? streamChunks(model, answer, usage)
          : delegationChunks(model, subagent, usage);
      for (const frame of frames) response.write(frame);
      response.end();
      return;
    }

    response
      .writeHead(200, { "content-type": "application/json" })
      .end(
        subagent === null ? completion(model, answer, usage) : delegation(model, subagent, usage),
      );
  });
});

server.listen(PORT, "127.0.0.1", () => {
  // Playwright waits on /health rather than on this line, but a server that
  // says nothing is one nobody can tell apart from a port already taken.
  console.log(`stub model server listening on http://127.0.0.1:${PORT}`);
});
