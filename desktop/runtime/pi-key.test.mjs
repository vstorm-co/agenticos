import { test } from "node:test";
import assert from "node:assert/strict";

async function reset(provider, key = "!private$key") {
  process.env.AGENTICOS_PI_KEY = key;
  process.env.AGENTICOS_PI_PROVIDER = provider;
  return (await import(`./pi-key.mjs?${crypto.randomUUID()}`)).default;
}
for (const provider of ["deepseek", "openrouter"]) {
  test(`${provider} receives only literal selected headers and the bootstrap env is removed`, async () => {
    const register = await reset(provider);
    const calls = [];
    await register({
      registerProvider: (id, configuration) =>
        calls.push({ id, configuration }),
    });
    assert.equal(calls.length, 1);
    const { id, configuration } = calls[0];
    assert.equal(id, provider);
    assert.equal(configuration.apiKey, "$!private$$key");
    assert.equal(configuration.headers.Authorization, "Bearer !private$$key");
    assert.equal(
      configuration.headers["x-api-key"],
      provider === "openrouter" ? "$!private$$key" : undefined,
    );
    assert.equal(process.env.AGENTICOS_PI_KEY, undefined);
    assert.equal(process.env.AGENTICOS_PI_PROVIDER, undefined);
    await register({
      registerProvider: (id, configuration) =>
        calls.push({ id, configuration }),
    });
    assert.deepEqual(calls[1], calls[0]);
  });
}
const model = {
  id: "account-model",
  context_length: 128000,
  max_output_length: 8192,
  pricing: {
    prompt: "0.0000001",
    completion: "0.0000002",
    input_cache_reads: "0.00000001",
    input_cache_writes: "0",
  },
  supported_endpoints: ["chat.completions"],
  supported_features: ["tools"],
  input_modalities: ["text"],
};
test("Inception models and limits come from the current authenticated chat catalog", async () => {
  const register = await reset("inception");
  const original = globalThis.fetch;
  const seen = [];
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(
        url,
        "https://api.inceptionlabs.ai/v1/chat/completions/models",
      );
      assert.equal(options.headers.Authorization, "Bearer !private$key");
      assert.equal(options.redirect, "error");
      return Response.json({ data: [model] });
    };
    await register({
      registerProvider: (id, configuration) => seen.push({ id, configuration }),
    });
    assert.equal(seen[0].configuration.models[0].id, "account-model");
    assert.equal(seen[0].configuration.models[0].contextWindow, 128000);
    assert.ok(
      Math.abs(seen[0].configuration.models[0].cost.input - 0.1) < 1e-12,
    );
    assert.equal(
      seen[0].configuration.baseUrl,
      "https://api.inceptionlabs.ai/v1",
    );
  } finally {
    globalThis.fetch = original;
  }
});
for (const data of [
  { data: [] },
  { data: [model, model] },
  { data: [{ ...model, max_output_length: 0 }] },
  { data: [{ ...model, supported_features: [] }] },
  { data: [{ ...model, pricing: { prompt: "invalid" } }] },
]) {
  test("unsupported or ambiguous Inception catalogs refuse before registration", async () => {
    const register = await reset("inception");
    const original = globalThis.fetch;
    try {
      globalThis.fetch = async () => Response.json(data);
      await assert.rejects(
        register({ registerProvider: () => assert.fail("not admitted") }),
      );
    } finally {
      globalThis.fetch = original;
    }
  });
}
