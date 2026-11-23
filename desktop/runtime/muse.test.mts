import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mkdtemp, writeFile, chmod, rm, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { EXPECTED_SCHEMA_FINGERPRINT } from "@muse-code/sdk";
import { MuseAdapter, SDK_VERSION, object } from "./muse.mts";

type Frame = Record<string, unknown>;

async function fixture(options: Frame = {}) {
  const root = await mkdtemp(join(tmpdir(), "agenticos-muse-test-"));
  const trace = join(root, "frames.jsonl");
  const program = join(root, "muse.mjs");
  await writeFile(
    program,
    `#!/usr/bin/env node
import { EventEmitter } from 'node:events';
import { appendFileSync, watchFile, unwatchFile } from 'node:fs';
const options = ${JSON.stringify(options)};
let selected = 'native-model';
let accountState=options.state??'accountLogin';
let cursor = 0;
const expireFile = ${JSON.stringify(join(root, "expire"))};
if(options.expireQuestion)watchFile(expireFile,{interval:10},stat=>{
 if(!stat.size)return;
 unwatchFile(expireFile);
 notify('userInput/settled',{userInputId:'human-one',answers:[],outcome:'timedOut',clarification:null,decidedAt:null,decidedByCommandId:null,reason:null});
 notify('item/completed',{item:{itemId:'expired-answer',kind:'agentMessage',revision:1,status:'completed',turnId:'native-turn',messagePhase:'finalAnswer',text:'Native timeout'}});
 notify('turn/completed',{terminal:'completed'});
});
const send = frame => process.stdout.write(JSON.stringify(frame) + '\\n');
const notify = (method, params) => send({jsonrpc:'2.0',method,params:{sessionId:'native-session',turnId:'native-turn',viewCursor:'c-'+(++cursor),sourceRange:{stream:{id:'stream',kind:'session'},first:{id:'event',sequence:cursor},last:{id:'event',sequence:cursor}},...params}});
const lines=new EventEmitter();
let incoming='';
process.stdin.setEncoding('utf8');
process.stdin.on('data',chunk=>{incoming+=chunk;let end;while((end=incoming.indexOf('\\n'))!==-1){const line=incoming.slice(0,end);incoming=incoming.slice(end+1);lines.emit('line',line);}});
process.stdin.on('end',()=>lines.emit('close'));
lines.on('line',line=>{
 const frame=JSON.parse(line),p=frame.params??{};
 appendFileSync(${JSON.stringify(trace)},JSON.stringify(frame)+'\\n');
 const reply=result=>send({jsonrpc:'2.0',id:frame.id,result:{...result,...(p.commandId?{commandId:p.commandId}:{})}});
 if(frame.method==='initialize') return reply({experimentalApi:true,grantedCapabilities:['sessionMcp'],museHome:'/private/native-home',platformFamily:'unix',platformOs:'linux',schema:{fingerprint:${JSON.stringify(EXPECTED_SCHEMA_FINGERPRINT)},version:1},serverInfo:{name:'fixture',version:options.version??${JSON.stringify(SDK_VERSION)}},sessionDurability:options.durability??'durable',userAgent:'fixture'});
 if(frame.method==='account/read') return reply({state:accountState,credentialRequired:options.credentialRequired??true,label:'private@example.test',apiKey:'never-export-this'});
 if(frame.method==='account/loginStart'){
  if(p.type!=='deviceCode')throw new Error('unsupported login');
  if(options.completeLogin)accountState='accountLogin';
  return reply({verificationUrl:options.verificationUrl??'https://login.example.test/device',userCode:'DEVICE-CODE'});
 }
 if(frame.method==='account/loginCancel')return reply({});
 if(frame.method==='account/logout'){if(accountState!=='envKey')accountState='loggedOut';return reply({});}
 if(frame.method==='session/start') return reply({session:{sessionId:'native-session',status:'idle'},viewCursor:'c-0'});
 if(frame.method==='session/resume') return reply({session:{sessionId:p.sessionId,status:'idle'},history:{mode:'none',items:[]},pendingRequests:[],viewCursor:'c-0'});
 if(frame.method==='model/list') return reply({providerId:'meta',profileId:null,source:'providerCatalog',models:(options.duplicate?[selected,selected]:['native-model','other-model']).map(modelId=>({modelId,providerId:'meta',profileId:null,displayLabel:modelId,isActive:modelId===selected,isDefault:false,description:null,cost:null,contextLimit:null,outputLimit:null,releaseDate:null}))});
 if(frame.method==='session/setModel'){if(!options.ignoreModel)selected=p.model.modelId;return reply({});}
 if(frame.method==='turn/start'){
  reply({disposition:'started',startedNewTurn:true,status:'accepted',turnId:'native-turn'});
  notify('turn/started',{});
  if(options.wait)return;
  if(options.questions){
   notify('userInput/requested',{userInputId:'human-one',itemId:'question-tool',toolCallId:'question-call',toolName:'ask',questions:options.questions});return;
  }
  if(options.approval){
   notify('approval/requested',{approvalId:'approval',availableChoices:[{choiceId:'once',decision:'approved',label:'Allow once',scope:'once'},{choiceId:'persist',decision:'approvedForSession',label:'Always allow',scope:'session'},{choiceId:'reject',decision:'denied',label:'Reject',scope:'once'}],currentRequirementId:{approvalId:'approval',sourceIndex:0},itemId:'tool-item',judgeEscalated:false,protectedWrite:false,rawArgs:'{}',taskId:'tool-item',toolCallId:'call',toolName:'Native tool',subject:{kind:options.subject??'shell'}});return;
  }
  notify('item/completed',{item:{itemId:'native-message',kind:'agentMessage',revision:1,status:'completed',turnId:'native-turn',messagePhase:'finalAnswer',text:'Native final answer'}});
  notify('turn/completed',{terminal:options.terminal??'completed',...(options.terminal==='failed'?{error:{kind:'auth',message:'SECRET-vendor-error'}}:{})});return;
 }
 if(frame.method==='userInput/answer'||frame.method==='userInput/cancel'){
  reply({status:'accepted',userInputId:'human-one'});
  notify('userInput/settled',{userInputId:'human-one',answers:p.answers??[],outcome:frame.method==='userInput/answer'?'answered':'cancelled',clarification:null,decidedAt:null,decidedByCommandId:p.commandId,reason:null});
  notify('item/completed',{item:{itemId:'human-answer',kind:'agentMessage',revision:1,status:'completed',turnId:'native-turn',messagePhase:'finalAnswer',text:'Question resolved'}});
  notify('turn/completed',{terminal:'completed'});return;
 }
 if(frame.method==='approval/decide'){
  reply({terminal:true});
  notify('item/completed',{item:{itemId:'answer',kind:'agentMessage',revision:1,status:'completed',turnId:'native-turn',text:'Approval resolved'}});
  notify('turn/completed',{terminal:'completed'});return;
 }
 if(frame.method==='turn/cancel'||frame.method==='turn/interrupt'){reply({status:'accepted'});notify('turn/completed',{terminal:'cancelled'});return;}
 if(frame.method==='initialized'||frame.id===undefined)return;
 send({jsonrpc:'2.0',id:frame.id,error:{code:-32601,message:'SECRET-unimplemented',data:{kind:'methodNotFound'}}});
});
lines.on('close',()=>process.exit(0));
`,
  );
  await chmod(program, 0o700);
  const frames: Frame[] = [];
  const adapter = new MuseAdapter(
    program,
    async (frame) => {
      frames.push(frame);
      if (
        frame.method === "_agenticos/request_questions" &&
        options.expireQuestion
      ) {
        await writeFile(join(root, "expire"), "settle");
      }
      if (
        frame.method === "_agenticos/request_questions" &&
        !options.holdQuestion
      ) {
        await adapter.accept({
          jsonrpc: "2.0",
          id: frame.id,
          result: options.humanResponse,
        });
      }
      if (frame.method === "session/request_permission") {
        const params = frame.params;
        assert.ok(
          typeof params === "object" && params !== null && "options" in params,
        );
        const choices = params.options;
        assert.ok(Array.isArray(choices));
        const chosen: unknown =
          choices.find(
            (choice: unknown) =>
              typeof choice === "object" &&
              choice !== null &&
              "kind" in choice &&
              choice.kind === "allow_once",
          ) ?? choices[0];
        assert.ok(
          typeof chosen === "object" && chosen !== null && "optionId" in chosen,
        );
        await adapter.accept({
          jsonrpc: "2.0",
          id: frame.id,
          result: {
            outcome: { outcome: "selected", optionId: chosen.optionId },
          },
        });
      }
    },
    options.accountControl === true,
  );
  let id = 0;
  async function request(method: string, params: Frame = {}) {
    const requestId = ++id;
    await adapter.accept({ jsonrpc: "2.0", id: requestId, method, params });
    const frame = frames.find((frame) => frame.id === requestId);
    assert.ok(frame);
    return frame;
  }
  async function initialize() {
    const initialized = await request("initialize", { protocolVersion: 1 });
    assert.ok(initialized.result);
    return initialized;
  }
  async function open() {
    await initialize();
    assert.ok((await request("authenticate", { methodId: "muse-cli" })).result);
    const opened = await request("session/new", {
      cwd: process.cwd(),
      mcpServers: [],
    });
    assert.ok(opened.result);
    return opened;
  }
  async function sent(): Promise<Frame[]> {
    return (await readFile(trace, "utf8"))
      .trim()
      .split("\n")
      .map((line: string): Frame => JSON.parse(line));
  }
  async function close() {
    await adapter.close();
    await rm(root, { recursive: true, force: true });
  }
  return { adapter, frames, request, initialize, open, sent, close, program };
}

for (const terminal of [
  "completed",
  "failed",
  "cancelled",
  "new-unknown-terminal",
]) {
  test(
    `the real SDK owns streaming and ${terminal} settlement`,
    { timeout: 5000 },
    async () => {
      const f = await fixture({ terminal });
      try {
        await f.open();
        const response = await f.request("session/prompt", {
          sessionId: "native-session",
          prompt: [{ type: "text", text: "Investigate" }],
        });
        assert.deepEqual(response.result, {
          stopReason: terminal === "completed" ? "end_turn" : "cancelled",
        });
        const output = JSON.stringify(f.frames);
        assert.ok(output.includes("Native final answer"));
        assert.ok(!output.includes("SECRET"));
        const sent = await f.sent();
        assert.equal(
          sent.filter((frame) => frame.method === "turn/start").length,
          1,
        );
        assert.ok(sent.every((frame) => frame.method !== "account/loginStart"));
      } finally {
        await f.close();
      }
    },
  );
}

test(
  "SDK/CLI versions and duplicate catalogs are refused before inference",
  { timeout: 5000 },
  async () => {
    for (const options of [
      { version: "0.0.0" },
      { duplicate: true },
      { durability: "ephemeral" },
      { durability: "new-unknown" },
    ]) {
      const f = await fixture(options);
      try {
        const initialized = await f.request("initialize", {
          protocolVersion: 1,
        });
        const result =
          "version" in options || "durability" in options
            ? initialized
            : await f.request("session/new", {
                cwd: process.cwd(),
                mcpServers: [],
              });
        assert.ok(result.error);
        assert.ok(
          !(await f.sent()).some((frame) => frame.method === "turn/start"),
        );
      } finally {
        await f.close();
      }
    }
  },
);

for (const state of [
  "accountLogin",
  "envKey",
  "apiKey",
  "loggedOut",
  "unknown",
]) {
  test(
    `credential reporting sanitizes the ${state} lane`,
    { timeout: 5000 },
    async () => {
      const f = await fixture({ state });
      try {
        await f.initialize();
        const status = await f.request("_auth/status");
        assert.deepEqual(status.result, { state, credentialRequired: true });
        const auth = await f.request("authenticate", { methodId: "muse-cli" });
        assert.equal(
          Boolean(auth.error),
          ["loggedOut", "unknown"].includes(state),
        );
        assert.ok(!JSON.stringify(f.frames).includes("private@example"));
        assert.ok(!JSON.stringify(f.frames).includes("never-export"));
      } finally {
        await f.close();
      }
    },
  );
}

test(
  "unapproved folders and MCP configuration cannot be injected",
  { timeout: 5000 },
  async () => {
    for (const params of [
      { cwd: tmpdir(), mcpServers: [] },
      { cwd: process.cwd(), mcpServers: [{ command: "injected" }] },
    ]) {
      const f = await fixture();
      try {
        await f.initialize();
        assert.ok((await f.request("session/new", params)).error);
        assert.ok(
          !(await f.sent()).some((frame) => frame.method === "session/start"),
        );
      } finally {
        await f.close();
      }
    }
  },
);

test(
  "model switching requires the SDK catalog and server acknowledgement",
  { timeout: 5000 },
  async () => {
    for (const ignoreModel of [false, true]) {
      const f = await fixture({ ignoreModel });
      try {
        await f.open();
        const result = await f.request("session/set_config_option", {
          sessionId: "native-session",
          configId: "model",
          value: "meta/other-model",
        });
        assert.equal(Boolean(result.error), ignoreModel);
        assert.ok(
          (
            await f.request("session/set_model", {
              sessionId: "foreign",
              modelId: "meta/native-model",
            })
          ).error,
        );
        assert.ok(
          (
            await f.request("session/set_model", {
              sessionId: "native-session",
              modelId: "unlisted",
            })
          ).error,
        );
      } finally {
        await f.close();
      }
    }
  },
);

test(
  "native cancellation reaches the owned SDK turn and returns no success",
  { timeout: 5000 },
  async () => {
    const f = await fixture({ wait: true });
    try {
      await f.open();
      const prompt = f.request("session/prompt", {
        sessionId: "native-session",
        prompt: [{ type: "text", text: "Wait" }],
      });
      for (
        let tries = 0;
        tries < 100 &&
        !(await f.sent()).some((frame) => frame.method === "turn/start");
        tries++
      )
        await new Promise((resolve) => setTimeout(resolve, 5));
      await f.adapter.accept({
        jsonrpc: "2.0",
        method: "session/cancel",
        params: { sessionId: "native-session" },
      });
      assert.ok((await prompt).error);
      assert.ok(
        (await f.sent()).some(
          (frame) =>
            frame.method === "turn/cancel" || frame.method === "turn/interrupt",
        ),
      );
    } finally {
      await f.close();
    }
  },
);

for (const subject of ["shell", "unrecognized-kind", "computerUseTakeover"]) {
  test(
    `approval choices preserve once-only scope for ${subject}`,
    { timeout: 5000 },
    async () => {
      const f = await fixture({ approval: true, subject });
      try {
        await f.open();
        const result = await f.request("session/prompt", {
          sessionId: "native-session",
          prompt: [{ type: "text", text: "Work" }],
        });
        assert.deepEqual(result.result, { stopReason: "end_turn" });
        const decision = (await f.sent()).find(
          (frame) => frame.method === "approval/decide",
        );
        assert.ok(
          decision &&
            typeof decision.params === "object" &&
            decision.params !== null &&
            "choiceId" in decision.params,
        );
        assert.equal(
          decision.params.choiceId,
          subject === "shell" ? "once" : "reject",
        );
      } finally {
        await f.close();
      }
    },
  );
}

test(
  "API-key mode refuses a saved account or saved-key fallback",
  { timeout: 5000 },
  async () => {
    for (const state of ["accountLogin", "apiKey", "envKey"]) {
      const f = await fixture({ state });
      try {
        await f.initialize();
        const response = await f.request("authenticate", {
          methodId: "muse-api-key",
        });
        assert.equal(Boolean(response.error), state !== "envKey");
      } finally {
        await f.close();
      }
    }
  },
);

test(
  "the subprocess frames only on LF and preserves split UTF-8 prompts",
  { timeout: 5000 },
  async () => {
    const f = await fixture();
    const child = spawn(
      process.execPath,
      [fileURLToPath(new URL("./muse.mts", import.meta.url)), f.program],
      { stdio: ["pipe", "pipe", "pipe"] },
    );
    const output: Frame[] = [];
    let pending = "";
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      pending += chunk;
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      for (const line of lines) {
        const value: unknown = JSON.parse(line);
        assert.ok(object(value));
        output.push(value);
      }
    });
    const exited = new Promise<number | null>((resolve) =>
      child.once("exit", resolve),
    );
    async function command(id: number, method: string, params: Frame) {
      const bytes = Buffer.from(
        JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n",
      );
      const split = bytes.indexOf(Buffer.from("🙂")) + 1;
      if (split > 0) {
        child.stdin.write(bytes.subarray(0, split));
        child.stdin.write(bytes.subarray(split));
      } else child.stdin.write(bytes);
      for (let tries = 0; tries < 400; tries++) {
        const result = output.find((frame) => frame.id === id);
        if (result) return result;
        await new Promise((resolve) => setTimeout(resolve, 5));
      }
      throw new Error("No adapter response");
    }
    try {
      assert.ok(
        (await command(1, "initialize", { protocolVersion: 1 })).result,
      );
      assert.ok(
        (
          await command(2, "session/new", {
            cwd: process.cwd(),
            mcpServers: [],
          })
        ).result,
      );
      assert.ok(
        (
          await command(3, "session/prompt", {
            sessionId: "native-session",
            prompt: [{ type: "text", text: "Line\u2028🙂" }],
          })
        ).result,
      );
      assert.ok(JSON.stringify(await f.sent()).includes("Line\u2028🙂"));
      child.stdin.end();
      assert.equal(await exited, 0);
    } finally {
      child.kill();
      await exited;
      await f.close();
    }
  },
);

const nativeQuestion = {
  id: "choice",
  header: "Approach",
  question: "Choose the approach",
  options: [
    { label: "A", preview: { format: "markdown", content: "Full preview" } },
    { label: "B" },
  ],
  selection: { mode: "single" },
};

for (const [name, response, expected] of [
  [
    "selection",
    {
      cancelled: false,
      answers: [{ skipped: false, selected: ["B"], answer: "" }],
    },
    [{ questionId: "choice", selectedLabel: "B" }],
  ],
  [
    "free text",
    {
      cancelled: false,
      answers: [{ skipped: false, selected: [], answer: "Custom answer" }],
    },
    [{ questionId: "choice", freeText: "Custom answer" }],
  ],
  [
    "unknown choice",
    {
      cancelled: false,
      answers: [{ skipped: false, selected: ["Injected"], answer: "" }],
    },
    undefined,
  ],
  ["cancelled", { cancelled: true, answers: [] }, undefined],
] as const) {
  test(
    `native human ${name} travels through the real SDK`,
    { timeout: 5000 },
    async () => {
      const f = await fixture({
        questions: [nativeQuestion],
        humanResponse: response,
      });
      try {
        await f.open();
        const result = await f.request("session/prompt", {
          sessionId: "native-session",
          prompt: [{ type: "text", text: "Ask" }],
        });
        assert.deepEqual(result.result, { stopReason: "end_turn" });
        const sent = await f.sent();
        const answer = sent.find(
          (frame) =>
            frame.method ===
            (expected ? "userInput/answer" : "userInput/cancel"),
        );
        assert.ok(answer);
        if (expected)
          assert.deepEqual(
            object(answer.params) && answer.params.answers,
            expected,
          );
        assert.ok(JSON.stringify(f.frames).includes("Full preview"));
      } finally {
        await f.close();
      }
    },
  );
}

test(
  "terminal cancellation closes a pending native question without waiting for a human",
  { timeout: 5000 },
  async () => {
    const f = await fixture({
      questions: [nativeQuestion],
      holdQuestion: true,
    });
    try {
      await f.open();
      const asking = f.request("session/prompt", {
        sessionId: "native-session",
        prompt: [{ type: "text", text: "Ask" }],
      });
      while (
        !f.frames.some(
          (frame) => frame.method === "_agenticos/request_questions",
        )
      )
        await new Promise((resolve) => setImmediate(resolve));
      const question = f.frames.find(
        (frame) => frame.method === "_agenticos/request_questions",
      );
      assert.ok(question);
      await f.adapter.accept({
        jsonrpc: "2.0",
        method: "session/cancel",
        params: { sessionId: "native-session" },
      });
      assert.ok((await asking).error);
      assert.ok(
        f.frames.some(
          (frame) =>
            frame.method === "_agenticos/cancel_request" &&
            object(frame.params) &&
            frame.params.id === question.id,
        ),
      );
      await f.adapter.accept({
        jsonrpc: "2.0",
        id: question.id,
        result: {
          cancelled: false,
          answers: [{ answer: "stale", selected: [], skipped: false }],
        },
      });
      assert.ok(
        !(await f.sent()).some((frame) => frame.method === "userInput/answer"),
      );
    } finally {
      await f.close();
    }
  },
);

test(
  "a native timeout closes the live card while the protocol observer keeps running",
  { timeout: 5000 },
  async () => {
    const f = await fixture({
      questions: [nativeQuestion],
      holdQuestion: true,
      expireQuestion: true,
    });
    try {
      await f.open();
      const result = await f.request("session/prompt", {
        sessionId: "native-session",
        prompt: [{ type: "text", text: "Ask" }],
      });
      assert.deepEqual(result.result, { stopReason: "end_turn" });
      assert.ok(
        f.frames.some((frame) => frame.method === "_agenticos/cancel_request"),
      );
      assert.ok(
        !(await f.sent()).some((frame) => frame.method === "userInput/answer"),
      );
    } finally {
      await f.close();
    }
  },
);

for (const accountControl of [false, true]) {
  test(
    `native-only account control is ${accountControl ? "admitted" : "refused in task mode"}`,
    { timeout: 5000 },
    async () => {
      const f = await fixture({
        accountControl,
        state: "loggedOut",
        completeLogin: true,
      });
      try {
        await f.initialize();
        const started = await f.request("_auth/login_start");
        if (!accountControl) {
          assert.ok(started.error);
          assert.ok(
            !(await f.sent()).some(
              (frame) => frame.method === "account/loginStart",
            ),
          );
          assert.ok((await f.request("_auth/logout")).error);
          assert.ok((await f.request("_auth/login_cancel")).error);
          return;
        }
        assert.deepEqual(started.result, {
          verificationUrl: "https://login.example.test/device",
          userCode: "DEVICE-CODE",
        });
        assert.deepEqual((await f.request("_auth/status")).result, {
          state: "accountLogin",
          credentialRequired: true,
        });
        assert.deepEqual((await f.request("_auth/logout")).result, {
          state: "loggedOut",
          credentialRequired: true,
        });
        assert.deepEqual((await f.request("_auth/login_cancel")).result, {
          state: "loggedOut",
          credentialRequired: true,
        });
        assert.ok(!JSON.stringify(f.frames).includes("private@example"));
      } finally {
        await f.close();
      }
    },
  );
}

for (const state of ["envKey", "apiKey", "accountLogin"]) {
  test(
    `device login cannot silently replace ${state}`,
    { timeout: 5000 },
    async () => {
      const f = await fixture({ accountControl: true, state });
      try {
        await f.initialize();
        assert.ok((await f.request("_auth/login_start")).error);
        assert.ok(
          !(await f.sent()).some(
            (frame) => frame.method === "account/loginStart",
          ),
        );
        const result = await f.request("_auth/logout");
        assert.deepEqual(result.result, {
          state: state === "envKey" ? "envKey" : "loggedOut",
          credentialRequired: true,
        });
      } finally {
        await f.close();
      }
    },
  );
}

for (const verificationUrl of [
  "http://login.example.test",
  "https://user:password@login.example.test",
  "javascript:alert(1)",
]) {
  test(
    `invalid device address ${verificationUrl.split(":")[0]} is refused`,
    { timeout: 5000 },
    async () => {
      const f = await fixture({
        accountControl: true,
        state: "loggedOut",
        verificationUrl,
      });
      try {
        await f.initialize();
        assert.ok((await f.request("_auth/login_start")).error);
      } finally {
        await f.close();
      }
    },
  );
}

test("only the native owner's exact scoped bridge reaches Muse per-session MCP configuration", async () => {
  const { PlatformBridge } = await import("./platform-bridge.mts");
  const bridge = new PlatformBridge(async () => {});
  await bridge.listen();
  const previousUrl = process.env.AGENTICOS_BRIDGE_URL;
  const previousToken = process.env.AGENTICOS_BRIDGE_TOKEN;
  Object.assign(process.env, bridge.environment());
  try {
    for (const admitted of [false, true]) {
      const f = await fixture();
      try {
        await f.initialize();
        await f.request("authenticate", { methodId: "muse-cli" });
        const server = bridge.serverDefinition();
        if (!admitted) server.command = "untrusted-program";
        const opened = await f.request("session/new", {
          cwd: process.cwd(),
          mcpServers: [server],
        });
        const starts = (await f.sent()).filter(
          (frame) => frame.method === "session/start",
        );
        if (!admitted) {
          assert.ok(opened.error);
          assert.equal(starts.length, 0);
        } else {
          assert.ok(opened.result);
          assert.equal(starts.length, 1);
          const params = starts[0]?.params;
          assert.ok(
            object(params) &&
              object(params.config) &&
              object(params.config.mcpServers),
          );
          const configured = params.config.mcpServers.agenticos_platform;
          assert.ok(object(configured));
          assert.equal(configured.transport, "streamableHttp");
          assert.equal(configured.url, bridge.url);
          assert.deepEqual(configured.headers, {
            Authorization: `Bearer ${bridge.environment().AGENTICOS_BRIDGE_TOKEN}`,
          });
        }
      } finally {
        await f.close();
      }
    }
  } finally {
    if (previousUrl === undefined) delete process.env.AGENTICOS_BRIDGE_URL;
    else process.env.AGENTICOS_BRIDGE_URL = previousUrl;
    if (previousToken === undefined) delete process.env.AGENTICOS_BRIDGE_TOKEN;
    else process.env.AGENTICOS_BRIDGE_TOKEN = previousToken;
    await bridge.close();
  }
});
