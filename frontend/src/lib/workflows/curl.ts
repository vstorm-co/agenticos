/**
 * A pasted cURL command, read into what an HTTP step is configured with.
 *
 * Only what the step can express is kept: the method, the URL, the headers and a
 * JSON body. A credential in the command - an `Authorization` header, `-u`, a
 * header or URL parameter named like a key - is lifted out rather than kept, so
 * it can go to the vault instead of into the graph.
 */

export type CurlCredential =
  | { kind: "bearer"; token: string }
  | { kind: "basic"; token: string; username: string }
  | { kind: "header"; name: string; token: string }
  | { kind: "query"; name: string; token: string };

export interface ParsedCurl {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  url: string;
  headers: Record<string, string>;
  /** The JSON body, or undefined when the command sends none. */
  body?: unknown;
  /** A body that is not JSON, which the step cannot send and was left out. */
  droppedBody: boolean;
  credential: CurlCredential | null;
}

export type CurlProblem = "notCurl" | "noUrl" | "badMethod" | "unclosedQuote";

const METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);
const WITH_VALUE = new Set([
  "-X",
  "--request",
  "-H",
  "--header",
  "-d",
  "--data",
  "--data-raw",
  "--data-binary",
  "--data-ascii",
  "--json",
  "-u",
  "--user",
  "--url",
  "-A",
  "--user-agent",
  "-e",
  "--referer",
  "-o",
  "--output",
  "-m",
  "--max-time",
  "--connect-timeout",
]);
const DATA = new Set(["-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--json"]);
const KEY_HEADER = /^(x-)?(api[-_]?key|apikey|token|access[-_]?token|auth[-_]?token|secret)$/i;
const KEY_PARAM = /^(api[-_]?key|apikey|key|token|access[-_]?token|auth[-_]?token)$/i;

/** The words of a shell command: quotes kept together, line continuations joined. */
export function shellWords(command: string): string[] | "unclosedQuote" {
  const words: string[] = [];
  let word = "";
  let started = false;
  let quote: "'" | '"' | null = null;
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index] as string;
    if (quote === "'") {
      if (char === "'") quote = null;
      else word += char;
      continue;
    }
    if (quote === '"') {
      if (char === '"') quote = null;
      else if (char === "\\" && index + 1 < command.length) {
        index += 1;
        word += command[index];
      } else word += char;
      continue;
    }
    if (char === "\\") {
      const next = command[index + 1];
      index += 1;
      if (next !== undefined && next !== "\n") {
        word += next;
        started = true;
      }
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      started = true;
      continue;
    }
    if (/\s/.test(char)) {
      if (started) words.push(word);
      word = "";
      started = false;
      continue;
    }
    word += char;
    started = true;
  }
  if (quote !== null) return "unclosedQuote";
  if (started) words.push(word);
  return words;
}

function header(line: string): [string, string] | null {
  const colon = line.indexOf(":");
  if (colon <= 0) return null;
  return [line.slice(0, colon).trim(), line.slice(colon + 1).trim()];
}

/** The credential an `Authorization` value carries, or null for a scheme it does not know. */
function fromAuthorization(value: string): CurlCredential | null {
  const [scheme = "", ...rest] = value.split(" ");
  const token = rest.join(" ").trim();
  if (scheme.toLowerCase() === "bearer" && token) return { kind: "bearer", token };
  if (scheme.toLowerCase() === "basic" && token) {
    try {
      const pair = atob(token);
      const colon = pair.indexOf(":");
      if (colon >= 0) {
        return { kind: "basic", username: pair.slice(0, colon), token: pair.slice(colon + 1) };
      }
    } catch {
      return null;
    }
  }
  return null;
}

/**
 * Read `command` as cURL, or say why it cannot be read.
 *
 * The first credential found wins; any other stays out of the result too, since
 * a step sends one credential and keeping the rest would store them in the graph.
 */
export function parseCurl(command: string): ParsedCurl | CurlProblem {
  const words = shellWords(command.trim());
  if (words === "unclosedQuote") return "unclosedQuote";
  if (words[0] !== "curl") return "notCurl";

  let method: string | null = null;
  let url: string | null = null;
  const headers: Record<string, string> = {};
  const data: string[] = [];
  let json = false;
  let credential: CurlCredential | null = null;

  for (let index = 1; index < words.length; index += 1) {
    let flag = words[index] as string;
    let value: string | undefined;
    const equals = flag.startsWith("--") ? flag.indexOf("=") : -1;
    if (equals > 0) {
      value = flag.slice(equals + 1);
      flag = flag.slice(0, equals);
    } else if (WITH_VALUE.has(flag)) {
      index += 1;
      value = words[index];
    }
    if (!flag.startsWith("-")) {
      url ??= flag;
      continue;
    }
    if (value === undefined) continue;
    if (flag === "-X" || flag === "--request") method = value.toUpperCase();
    else if (flag === "--url") url = value;
    else if (DATA.has(flag)) {
      data.push(value);
      json ||= flag === "--json";
    } else if (flag === "-u" || flag === "--user") {
      const colon = value.indexOf(":");
      credential ??= {
        kind: "basic",
        username: colon >= 0 ? value.slice(0, colon) : value,
        token: colon >= 0 ? value.slice(colon + 1) : "",
      };
    } else if (flag === "-H" || flag === "--header") {
      const parsed = header(value);
      if (parsed === null) continue;
      const [name, text] = parsed;
      if (name.toLowerCase() === "authorization") {
        credential ??= fromAuthorization(text);
      } else if (KEY_HEADER.test(name)) {
        credential ??= { kind: "header", name, token: text };
      } else if (name.toLowerCase() !== "content-length") {
        headers[name] = text;
      }
    }
  }

  if (url === null) return "noUrl";
  let address: URL;
  try {
    address = new URL(url);
  } catch {
    return "noUrl";
  }
  for (const [name, text] of [...address.searchParams]) {
    if (!KEY_PARAM.test(name)) continue;
    credential ??= { kind: "query", name, token: text };
    address.searchParams.delete(name);
  }

  const resolved = method ?? (data.length > 0 ? "POST" : "GET");
  if (!METHODS.has(resolved)) return "badMethod";

  let body: unknown;
  let droppedBody = false;
  if (data.length > 0) {
    try {
      body = JSON.parse(data.join("&"));
    } catch {
      droppedBody = true;
    }
  }
  if (json || body !== undefined) {
    delete headers["Content-Type"];
    delete headers["content-type"];
  }
  return {
    method: resolved as ParsedCurl["method"],
    url: address.toString(),
    headers,
    ...(body === undefined ? {} : { body }),
    droppedBody,
    credential,
  };
}
