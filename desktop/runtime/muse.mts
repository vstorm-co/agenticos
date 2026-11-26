import { once } from "node:events";
import { realpath } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  MuseClient,
  readSessionDurability,
  type ApprovalHandler,
  type ApprovalDecisionInput,
  type Session,
} from "@muse-code/sdk";

export const SDK_VERSION = "1.4.23";
const MAX_FRAME = 4 << 20;
type ApprovalRequestParams = Parameters<ApprovalHandler>[0];
type ModelCatalogEntry = Awaited<
  ReturnType<MuseClient["listModels"]>
>["models"][number];
type NativeInput = ReturnType<Session["fold"]["pendingUserInputs"]>[number];
type NativeAnswer = Parameters<Session["answerUserInput"]>[1][number];
type JsonObject = Record<string, unknown>;
type Emit = (frame: JsonObject) => Promise<void>;

export function object(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value || value.length > 4096) {
    throw new Error("Invalid request field");
  }
  return value;
}

/** Only the native process owner supplies the executable and working directory. */
export class MuseAdapter {
  private client: MuseClient | undefined;
  private session: Session | undefined;
  private active: AbortController | undefined;
  private requests = new Map<string, (value: unknown) => void>();
  private models = new Map<string, ModelCatalogEntry>();
  private retiredRequests = new Set<string>();
  private handledInputs = new Set<string>();
  private inputs = new Map<
    string,
    { controller: AbortController; task: Promise<void> }
  >();
  private approvalFailed = false;
  private closing = false;
  private running = false;
  private observationFailed = false;
  private observer: Promise<void> | undefined;
  private observing: AbortController | undefined;

  private readonly program: string;
  private readonly emit: Emit;
  private readonly accountControl: boolean;

  constructor(program: string, emit: Emit, accountControl = false) {
    this.program = program;
    this.emit = emit;
    this.accountControl = accountControl;
  }

  async accept(value: unknown): Promise<void> {
    if (!object(value) || value.jsonrpc !== "2.0")
      throw new Error("Invalid RPC frame");
    const id = value.id;
    if (
      typeof id === "string" &&
      typeof value.method !== "string" &&
      this.retiredRequests.has(id)
    )
      return;
    if (
      typeof id === "string" &&
      typeof value.method !== "string" &&
      this.requests.has(id)
    ) {
      const reply = this.requests.get(id);
      this.requests.delete(id);
      this.retire(id);
      reply?.(value.result);
      return;
    }
    if (typeof value.method !== "string") throw new Error("Invalid RPC method");
    const params = object(value.params) ? value.params : {};
    if (value.method === "session/cancel") {
      if (this.session && params.sessionId === this.session.sessionId)
        this.active?.abort();
      return;
    }
    if (typeof id !== "string" && typeof id !== "number")
      throw new Error("A request needs an id");
    let admitted = false;
    try {
      if (this.running) throw new Error("Another command is active");
      this.running = true;
      admitted = true;
      const result = await this.dispatch(value.method, params);
      await this.emit({ jsonrpc: "2.0", id, result });
    } catch {
      // Vendor errors may contain paths, account labels or credential material.
      await this.emit({
        jsonrpc: "2.0",
        id,
        error: {
          code: -32000,
          message:
            "Muse refused the operation. Check its login, model, quota and matching CLI version.",
        },
      });
    } finally {
      if (admitted) this.running = false;
    }
  }

  private retire(id: string): void {
    this.retiredRequests.add(id);
    if (this.retiredRequests.size > 128) {
      const first = this.retiredRequests.values().next().value;
      if (first !== undefined) this.retiredRequests.delete(first);
    }
  }

  private async requestInput(
    prompt: NativeInput,
    signal: AbortSignal,
  ): Promise<unknown> {
    if (this.requests.size >= 16)
      throw new Error("Too many pending native inputs");
    if (signal.aborted || this.closing) return undefined;
    const id = `muse-question-${crypto.randomUUID()}`;
    let cancel: () => void = () => {};
    const reply = new Promise<unknown>((resolve) => {
      this.requests.set(id, resolve);
      cancel = () => resolve(undefined);
    });
    signal.addEventListener("abort", cancel, { once: true });
    const timer =
      prompt.autoResolutionMs === undefined
        ? undefined
        : setTimeout(
            cancel,
            Math.min(
              3600000,
              Math.max(1, prompt.autoResolutionMs * prompt.questions.length),
            ),
          );
    try {
      await this.emit({
        jsonrpc: "2.0",
        id,
        method: "_agenticos/request_questions",
        params: {
          questions: prompt.questions.map((question) => ({
            id: question.id,
            header: question.header,
            question:
              question.question +
              question.options
                .map((option) =>
                  option.preview
                    ? `\n\n${option.label}:\n${option.preview.content}`
                    : "",
                )
                .join(""),
            options: question.options.map((option) => ({
              label: option.label,
              ...(option.description === undefined
                ? {}
                : { description: option.description }),
            })),
            multi_select: question.selection.mode === "multiple",
            allow_custom: true,
            max_answer_length: 500,
            ...(question.selection.mode === "multiple"
              ? {
                  min_selections: question.selection.minSelections ?? 1,
                  max_selections:
                    question.selection.maxSelections ?? question.options.length,
                }
              : {}),
          })),
        },
      });
      return await reply;
    } finally {
      signal.removeEventListener("abort", cancel);
      if (timer !== undefined) clearTimeout(timer);
      if (this.requests.delete(id)) {
        this.retire(id);
        await this.emit({
          jsonrpc: "2.0",
          method: "_agenticos/cancel_request",
          params: { id },
        });
      }
    }
  }

  private async settleInput(
    session: Session,
    prompt: NativeInput,
    signal: AbortSignal,
  ): Promise<void> {
    if (
      prompt.questions.length < 1 ||
      prompt.questions.length > 3 ||
      prompt.questions.some(
        (question) =>
          question.selection.mode !== "single" &&
          question.selection.mode !== "multiple",
      )
    )
      throw new Error("Unsupported native question schema");
    const response = await this.requestInput(prompt, signal);
    if (
      !session.fold
        .pendingUserInputs()
        .some((item) => item.userInputId === prompt.userInputId)
    )
      return;
    const answers: NativeAnswer[] = [];
    if (
      object(response) &&
      response.cancelled === false &&
      Array.isArray(response.answers) &&
      response.answers.length === prompt.questions.length
    ) {
      for (const [index, question] of prompt.questions.entries()) {
        const answer: unknown = response.answers[index];
        if (
          !object(answer) ||
          answer.skipped !== false ||
          !Array.isArray(answer.selected) ||
          typeof answer.answer !== "string"
        )
          break;
        const selected = answer.selected.filter(
          (value: unknown): value is string => typeof value === "string",
        );
        if (
          selected.length !== answer.selected.length ||
          new Set(selected).size !== selected.length ||
          !selected.every((label) =>
            question.options.some((option) => option.label === label),
          )
        )
          break;
        if (answer.answer) {
          if (answer.answer.length > 500) break;
          answers.push({ questionId: question.id, freeText: answer.answer });
        } else if (
          question.selection.mode === "single" &&
          selected.length === 1 &&
          selected[0] !== undefined
        ) {
          answers.push({ questionId: question.id, selectedLabel: selected[0] });
        } else if (
          question.selection.mode === "multiple" &&
          selected.length >= (question.selection.minSelections ?? 1) &&
          selected.length <=
            (question.selection.maxSelections ?? question.options.length)
        ) {
          answers.push({ questionId: question.id, selectedLabels: selected });
        } else break;
      }
    }
    try {
      if (answers.length === prompt.questions.length)
        await session.answerUserInput(prompt.userInputId, answers);
      else if (!this.closing)
        await this.client?.command("userInput/cancel", {
          sessionId: session.sessionId,
          userInputId: prompt.userInputId,
        });
    } catch (error) {
      // A host timeout can win while the human's reply is in flight. Only the
      // SDK's folded settlement permits dropping that now-stale answer.
      if (
        session.fold
          .pendingUserInputs()
          .some((item) => item.userInputId === prompt.userInputId)
      )
        throw error;
    }
  }

  private pendingInputs(session: Session): void {
    const pending = session.fold.pendingUserInputs();
    const ids = new Set(pending.map((prompt) => prompt.userInputId));
    for (const [id, input] of this.inputs) {
      if (!ids.has(id)) input.controller.abort();
    }
    for (const prompt of pending) {
      if (this.handledInputs.has(prompt.userInputId)) continue;
      if (this.handledInputs.size >= 128 || this.inputs.size >= 8)
        throw new Error("Native question limit exceeded");
      this.handledInputs.add(prompt.userInputId);
      const controller = new AbortController();
      const task = this.settleInput(session, prompt, controller.signal)
        .catch(() => {
          this.observationFailed = true;
          this.active?.abort(new Error("Muse human input failed"));
        })
        .finally(() => {
          this.inputs.delete(prompt.userInputId);
        });
      this.inputs.set(prompt.userInputId, { controller, task });
    }
  }

  private async update(update: JsonObject): Promise<void> {
    if (!this.session) throw new Error("No owned session");
    await this.emit({
      jsonrpc: "2.0",
      method: "session/update",
      params: { sessionId: this.session.sessionId, update },
    });
  }

  private platformConfiguration(
    servers: unknown,
  ): NonNullable<Parameters<MuseClient["startSession"]>[0]>["config"] {
    if (!Array.isArray(servers))
      throw new Error("Unadmitted MCP configuration");
    const endpoint = process.env.AGENTICOS_BRIDGE_URL;
    const token = process.env.AGENTICOS_BRIDGE_TOKEN;
    if (!endpoint && !token && servers.length === 0) return undefined;
    if (
      !endpoint ||
      !/^http:\/\/127\.0\.0\.1:[0-9]+\/mcp$/.test(endpoint) ||
      !token ||
      !/^[a-f0-9]{64}$/.test(token) ||
      servers.length !== 1
    )
      throw new Error("Unadmitted platform bridge");
    const server: unknown = servers[0];
    if (
      !object(server) ||
      server.name !== "agenticos_platform" ||
      server.command !== process.execPath ||
      !Array.isArray(server.args) ||
      server.args.length !== 2 ||
      server.args[0] !==
        fileURLToPath(new URL("platform-bridge.mts", import.meta.url)) ||
      server.args[1] !== "client" ||
      !Array.isArray(server.env) ||
      server.env.length !== 2
    )
      throw new Error("Unadmitted platform bridge");
    const env = new Map<string, string>();
    for (const entry of server.env) {
      if (
        !object(entry) ||
        typeof entry.name !== "string" ||
        typeof entry.value !== "string" ||
        env.has(entry.name)
      )
        throw new Error("Invalid bridge environment");
      env.set(entry.name, entry.value);
    }
    if (
      env.get("AGENTICOS_BRIDGE_URL") !== endpoint ||
      env.get("AGENTICOS_BRIDGE_TOKEN") !== token
    )
      throw new Error("Wrong bridge authority");
    return {
      mcpServers: {
        agenticos_platform: {
          transport: "streamableHttp",
          url: endpoint,
          headers: { Authorization: `Bearer ${token}` },
          mode: "required",
        },
      },
    };
  }

  private async catalog(): Promise<JsonObject> {
    if (!this.client || !this.session) throw new Error("No owned session");
    const catalog = await this.client.listModels({
      sessionId: this.session.sessionId,
    });
    if (catalog.models.length > 128) throw new Error("Excessive catalog");
    const models = new Map<string, ModelCatalogEntry>();
    for (const model of catalog.models) {
      const id = `${model.providerId}/${model.modelId}`;
      if (id.length > 256 || models.has(id) || model.displayLabel.length > 256)
        throw new Error("Ambiguous catalog");
      models.set(id, model);
    }
    this.models = models;
    const current = [...models].find(([, model]) => model.isActive)?.[0];
    return {
      configOptions: [
        {
          id: "model",
          name: "Model",
          category: "model",
          type: "select",
          options: [...models].map(([value, model]) => ({
            value,
            name: model.displayLabel,
          })),
          ...(current ? { currentValue: current } : {}),
        },
      ],
    };
  }

  private async approval(
    request: ApprovalRequestParams,
  ): Promise<ApprovalDecisionInput> {
    const choices = request.availableChoices.filter(
      (choice) =>
        choice.scope === "once" &&
        (choice.decision === "approved" ||
          choice.decision === "denied" ||
          choice.decision === "abort"),
    );
    if (!choices.length || this.requests.size >= 16)
      throw new Error("Unsupported approval choices");
    const known = [
      "shell",
      "fileAccess",
      "network",
      "unixSocket",
      "process",
      "tool",
    ].includes(request.subject.kind);
    // Unknown subjects and computer takeover cannot inherit generic edit consent.
    const offered = known
      ? choices
      : choices.filter((choice) => choice.decision !== "approved");
    const id = `muse-approval-${request.approvalId}-${crypto.randomUUID()}`;
    const reply = new Promise<unknown>((resolve) =>
      this.requests.set(id, resolve),
    );
    await this.emit({
      jsonrpc: "2.0",
      id,
      method: "session/request_permission",
      params: {
        sessionId: request.sessionId,
        toolCall: {
          toolCallId: request.toolCallId,
          title: request.toolName,
          kind: request.subject.kind === "shell" ? "execute" : "other",
        },
        options: offered.map((choice) => ({
          optionId: choice.choiceId,
          name: choice.label,
          kind: choice.decision === "approved" ? "allow_once" : "reject_once",
        })),
      },
    });
    const result = await reply;
    if (
      !object(result) ||
      !object(result.outcome) ||
      result.outcome.outcome !== "selected"
    )
      throw new Error("Approval cancelled");
    const selected = result.outcome.optionId;
    const chosen = offered.find((choice) => choice.choiceId === selected);
    if (!chosen) throw new Error("Unoffered approval");
    return { choiceId: chosen.choiceId };
  }

  private async observe(session: Session, signal: AbortSignal): Promise<void> {
    const textLengths = new Map<string, number>();
    const started = new Set<string>();
    try {
      this.pendingInputs(session);
      for await (const event of session.events({ signal })) {
        const item = event.item;
        if (
          item?.kind === "agentMessage" &&
          item.messagePhase !== "commentary" &&
          typeof item.text === "string"
        ) {
          const before = textLengths.get(item.itemId) ?? 0;
          if (item.text.length < before)
            throw new Error("Non-append message revision");
          const delta = item.text.slice(before);
          textLengths.set(item.itemId, item.text.length);
          if (delta)
            await this.update({
              sessionUpdate: "agent_message_chunk",
              content: { type: "text", text: delta },
            });
        }
        if (item?.kind === "toolCall") {
          if (!started.has(item.itemId)) {
            started.add(item.itemId);
            await this.update({
              sessionUpdate: "tool_call",
              toolCallId: item.itemId,
              title: item.displayLabel?.active ?? "Muse tool",
              kind: "other",
              status: "in_progress",
            });
          }
          if (item.status !== "inProgress")
            await this.update({
              sessionUpdate: "tool_call_update",
              toolCallId: item.itemId,
              status: item.status === "completed" ? "completed" : "failed",
            });
        }
        this.pendingInputs(session);
      }
    } finally {
      const inputs = [...this.inputs.values()];
      for (const input of inputs) input.controller.abort();
      await Promise.all(inputs.map((input) => input.task));
      this.inputs.clear();
    }
  }

  private async stopObserver(): Promise<void> {
    this.observing?.abort();
    await this.observer;
    this.observer = undefined;
    this.observing = undefined;
  }

  private async opened(session: Session): Promise<JsonObject> {
    this.session = session;
    session.onApproval((request) => this.approval(request));
    session.onApprovalError(() => {
      this.approvalFailed = true;
      this.active?.abort(new Error("Muse approval failed"));
    });
    this.observing = new AbortController();
    this.observer = this.observe(session, this.observing.signal);
    // Observe failures immediately; close still awaits the same promise.
    this.observer.catch(() => {
      this.observationFailed = true;
      this.active?.abort(new Error("Muse event stream failed"));
    });
    return { sessionId: session.sessionId, ...(await this.catalog()) };
  }

  private async dispatch(
    method: string,
    params: JsonObject,
  ): Promise<JsonObject> {
    if (this.closing) throw new Error("Closed adapter");
    if (method === "initialize") {
      if (this.client || params.protocolVersion !== 1)
        throw new Error("Unsupported initialization");
      this.client = await MuseClient.spawn({
        museBin: this.program,
        args: ["serve"],
        cwd: process.cwd(),
        clientInfo: { name: "agenticos", version: "1" },
        capabilities: { experimentalApi: true, userInputDialogs: true },
        refuseDeclaredBreakingSchema: true,
        signal: AbortSignal.timeout(30000),
      });
      if (
        this.client.initializeResult.serverInfo.version !== SDK_VERSION ||
        readSessionDurability(this.client.initializeResult).kind !== "durable"
      ) {
        const unsupported = this.client;
        this.client = undefined;
        await unsupported.close();
        throw new Error("SDK/CLI version or durable-session contract mismatch");
      }
      return {
        protocolVersion: 1,
        agentCapabilities: {
          loadSession:
            readSessionDurability(this.client.initializeResult).kind ===
            "durable",
        },
        agentInfo: { name: "Muse SDK", version: SDK_VERSION },
        authMethods: [
          { id: "muse-cli", name: "Muse CLI configuration" },
          { id: "muse-api-key", name: "Muse environment API key" },
        ],
      };
    }
    const client = this.client;
    if (!client) throw new Error("Initialize first");
    if (this.active) throw new Error("Turn already active");
    if (method === "authenticate") {
      if (params.methodId !== "muse-cli" && params.methodId !== "muse-api-key")
        throw new Error("Unsupported auth method");
      const state = await client.request("account/read");
      if (
        !state.credentialRequired ||
        !["envKey", "apiKey", "accountLogin"].includes(
          typeof state.state === "string" ? state.state : "",
        )
      )
        throw new Error("Muse login required");
      if (params.methodId === "muse-api-key" && state.state !== "envKey")
        throw new Error("Required environment key was not confirmed");
      return {};
    }
    if (
      ["_auth/login_start", "_auth/login_cancel", "_auth/logout"].includes(
        method,
      )
    ) {
      if (!this.accountControl || this.session)
        throw new Error("Account control is native-only");
      if (method === "_auth/login_start") {
        const state = await client.request("account/read");
        if (state.state !== "loggedOut" || state.credentialRequired !== true)
          throw new Error(
            "Log out or remove the overriding environment key first",
          );
        const started = await client.command("account/loginStart", {
          type: "deviceCode",
        });
        if (
          typeof started.verificationUrl !== "string" ||
          typeof started.userCode !== "string" ||
          !started.userCode.trim() ||
          /\p{C}/u.test(started.userCode) ||
          started.userCode.length > 128
        )
          throw new Error("Invalid device sign-in response");
        const url = new URL(started.verificationUrl);
        if (
          url.protocol !== "https:" ||
          url.username ||
          url.password ||
          started.verificationUrl.length > 2048
        )
          throw new Error("Invalid device sign-in URL");
        return { verificationUrl: url.href, userCode: started.userCode };
      }
      await client.command(
        method === "_auth/logout" ? "account/logout" : "account/loginCancel",
        {},
      );
      const state = await client.request("account/read");
      return {
        state: state.state,
        credentialRequired: state.credentialRequired,
      };
    }
    if (method === "_auth/status") {
      const state = await client.request("account/read");
      return {
        state: state.state,
        credentialRequired: state.credentialRequired,
      };
    }
    if (method === "session/new" || method === "session/load") {
      if (
        this.session ||
        (await realpath(text(params.cwd))) !== (await realpath(process.cwd()))
      )
        throw new Error("Unapproved workspace");
      const config = this.platformConfiguration(params.mcpServers);
      const session =
        method === "session/load"
          ? await client.resumeSession({
              sessionId: text(params.sessionId),
              ...(config ? { config } : {}),
              onApproval: (request) => this.approval(request),
              onApprovalError: () => {
                this.approvalFailed = true;
                this.active?.abort();
              },
            })
          : await client.startSession({
              workspaceRoot: process.cwd(),
              ...(config ? { config } : {}),
            });
      return this.opened(session);
    }
    const session = this.session;
    if (!session || params.sessionId !== session.sessionId)
      throw new Error("Foreign session");
    if (
      method === "session/set_model" ||
      method === "session/set_config_option"
    ) {
      if (method === "session/set_config_option" && params.configId !== "model")
        throw new Error("Unsupported configuration");
      const selected = text(
        method === "session/set_model" ? params.modelId : params.value,
      );
      const model = this.models.get(selected);
      if (!model) throw new Error("Unlisted model");
      await session.setModel({
        modelId: model.modelId,
        providerId: model.providerId,
        profileId: model.profileId,
      });
      const acknowledged = await this.catalog();
      if (!this.models.get(selected)?.isActive)
        throw new Error("Model selection was not acknowledged");
      return acknowledged;
    }
    if (method !== "session/prompt") throw new Error("Unsupported operation");
    if (
      !Array.isArray(params.prompt) ||
      !params.prompt.length ||
      params.prompt.some(
        (part) =>
          !object(part) ||
          part.type !== "text" ||
          typeof part.text !== "string",
      )
    )
      throw new Error("Text prompt required");
    const prompt = params.prompt
      .map((part) =>
        object(part) && typeof part.text === "string" ? part.text : "",
      )
      .join("\n");
    if (this.observationFailed) throw new Error("The event observer failed");
    this.active = new AbortController();
    try {
      const result = await session.run(prompt, { signal: this.active.signal });
      if (this.observationFailed) throw new Error("The event observer failed");
      if (
        result.outcome.kind !== "completed" ||
        result.outcome.params.terminal !== "completed"
      )
        return { stopReason: "cancelled" };
      if (!result.finalText?.trim()) throw new Error("No final answer");
      await this.stopObserver();
      await this.update({
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: result.finalText },
        _meta: { agenticosFinalAnswer: true },
      });
      return { stopReason: "end_turn" };
    } finally {
      this.active = undefined;
      await this.stopObserver();
    }
  }

  async close(): Promise<void> {
    if (this.closing) return;
    this.closing = true;
    this.active?.abort();
    for (const resolve of this.requests.values()) resolve(undefined);
    this.requests.clear();
    try {
      await this.client?.close();
    } finally {
      await this.stopObserver();
    }
  }
}

export async function main(): Promise<void> {
  const program = text(process.argv[2]);
  const emit: Emit = async (frame) => {
    const line = JSON.stringify(frame) + "\n";
    if (Buffer.byteLength(line) > MAX_FRAME)
      throw new Error("Excessive output frame");
    if (!process.stdout.write(line)) await once(process.stdout, "drain");
  };
  const adapter = new MuseAdapter(
    program,
    emit,
    process.argv[3] === "--native-account-control",
  );
  const pending = new Set<Promise<void>>();
  let buffer = Buffer.alloc(0);
  try {
    for await (const chunk of process.stdin) {
      if (!Buffer.isBuffer(chunk)) throw new Error("Binary input required");
      buffer = Buffer.concat([buffer, chunk]);
      let end: number;
      while ((end = buffer.indexOf(10)) !== -1) {
        if (end > MAX_FRAME || pending.size >= 32)
          throw new Error("Excessive input");
        const line = buffer.subarray(0, end).toString("utf8");
        buffer = buffer.subarray(end + 1);
        const frame: unknown = JSON.parse(line);
        const work = adapter.accept(frame);
        pending.add(work);
        work
          .finally(() => pending.delete(work))
          .catch(() => {
            process.exitCode = 1;
            process.stdin.destroy();
          });
      }
      if (buffer.length > MAX_FRAME)
        throw new Error("Excessive unfinished frame");
    }
    if (buffer.length) throw new Error("Truncated frame");
  } finally {
    await adapter.close();
    await Promise.allSettled(pending);
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main().catch(() => {
    process.exitCode = 1;
  });
}
