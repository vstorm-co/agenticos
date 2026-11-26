/**
 * @typedef {{ input: number, output: number, cacheRead: number, cacheWrite: number }} ModelCost
 * @typedef {{ type: 'chat', id: string, name: string, reasoning: boolean, input: string[], contextWindow: number, maxTokens: number, cost: ModelCost }} NativeModel
 * @typedef {{ apiKey: string, headers: Record<string, string>, baseUrl?: string, api?: string, models?: NativeModel[] }} ProviderConfig
 * @typedef {{ registerProvider: (name: string, config: ProviderConfig) => void }} PiExtension
 */

/** @type {{ key: string, provider: string } | undefined} */
let selected;

/** @param {unknown} value @returns {value is Record<string, unknown>} */
function record(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
/** @param {unknown} value @returns {value is string[]} */
function strings(value) {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

/** @param {unknown} value @returns {number} */
function price(value) {
  const number =
    typeof value === "string" && value.trim() ? Number(value) : NaN;
  if (!Number.isFinite(number) || number < 0)
    throw new Error("Unsupported Inception pricing metadata");
  const perMillion = number * 1000000;
  if (!Number.isFinite(perMillion))
    throw new Error("Unsupported Inception pricing metadata");
  return perMillion;
}

/** @param {unknown} value @returns {NativeModel} */
function model(value) {
  if (
    !record(value) ||
    typeof value.id !== "string" ||
    !value.id ||
    value.id.length > 256 ||
    /\s|\p{C}/u.test(value.id) ||
    typeof value.context_length !== "number" ||
    !Number.isSafeInteger(value.context_length) ||
    value.context_length < 1 ||
    typeof value.max_output_length !== "number" ||
    !Number.isSafeInteger(value.max_output_length) ||
    value.max_output_length < 1 ||
    value.max_output_length > value.context_length ||
    !strings(value.supported_endpoints) ||
    !value.supported_endpoints.includes("chat.completions") ||
    !strings(value.supported_features) ||
    !value.supported_features.includes("tools") ||
    !strings(value.input_modalities) ||
    !value.input_modalities.includes("text") ||
    !record(value.pricing)
  )
    throw new Error("Unsupported Inception chat model metadata");
  return {
    type: "chat",
    id: value.id,
    name: value.id,
    reasoning: false,
    input: ["text"],
    contextWindow: value.context_length,
    maxTokens: value.max_output_length,
    cost: {
      input: price(value.pricing.prompt),
      output: price(value.pricing.completion),
      cacheRead: price(value.pricing.input_cache_reads),
      cacheWrite: price(value.pricing.input_cache_writes),
    },
  };
}

/** A key-free extension; the native owner supplies one ephemeral provider key. @param {PiExtension} pi */
export default async function registerSelectedKey(pi) {
  if (selected === undefined) {
    const key = process.env.AGENTICOS_PI_KEY;
    const provider = process.env.AGENTICOS_PI_PROVIDER;
    delete process.env.AGENTICOS_PI_KEY;
    delete process.env.AGENTICOS_PI_PROVIDER;
    if (
      !key ||
      !provider ||
      !["inception", "deepseek", "openrouter"].includes(provider)
    )
      throw new Error("A selected AgenticOS Pi provider key is required");
    selected = Object.freeze({ key, provider });
  }
  const { key, provider } = selected;
  // Pi interprets $ references and a leading ! command; these values are literals.
  const literal = key.replaceAll("$", () => "$$");
  const apiKey = literal.startsWith("!") ? "$" + literal : literal;
  /** @type {Record<string, string>} */
  const headers = { Authorization: "Bearer " + literal };
  if (provider === "openrouter") headers["x-api-key"] = apiKey;
  if (provider !== "inception") {
    pi.registerProvider(provider, { apiKey, headers });
    return;
  }
  const response = await fetch(
    "https://api.inceptionlabs.ai/v1/chat/completions/models",
    {
      headers: { Authorization: "Bearer " + key },
      redirect: "error",
      signal: AbortSignal.timeout(15000),
    },
  );
  if (!response.ok || !response.body)
    throw new Error("Inception model discovery was refused");
  const reader = response.body.getReader();
  let length = 0;
  /** @type {Uint8Array[]} */
  const chunks = [];
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 2 * 1024 * 1024)
        throw new Error("Inception catalog limit exceeded");
      chunks.push(value);
    }
  } finally {
    await reader.cancel();
  }
  const buffer = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    buffer.set(chunk, offset);
    offset += chunk.length;
  }
  /** @type {unknown} */
  const data = JSON.parse(
    new TextDecoder("utf-8", { fatal: true }).decode(buffer),
  );
  if (
    !record(data) ||
    !Array.isArray(data.data) ||
    !data.data.length ||
    data.data.length > 128
  )
    throw new Error("Unsupported Inception model catalog");
  const models = data.data.map(model);
  if (new Set(models.map((model) => model.id)).size !== models.length)
    throw new Error("Ambiguous Inception catalog");
  pi.registerProvider("inception", {
    apiKey,
    headers,
    baseUrl: "https://api.inceptionlabs.ai/v1",
    api: "openai-completions",
    models,
  });
}
