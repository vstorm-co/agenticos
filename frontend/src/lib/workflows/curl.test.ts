import { describe, expect, it } from "vitest";

import { parseCurl, shellWords } from "./curl";

describe("shellWords", () => {
  it("keeps quoted words together and joins continued lines", () => {
    expect(shellWords(`curl 'a b' "c \\"d\\"" e\\ f \\\n  g`)).toEqual([
      "curl",
      "a b",
      'c "d"',
      "e f",
      "g",
    ]);
  });

  it("says when a quote is never closed", () => {
    expect(shellWords("curl 'open")).toBe("unclosedQuote");
  });
});

describe("parseCurl", () => {
  it("reads the method, URL, headers and a JSON body", () => {
    expect(
      parseCurl(
        `curl -X PUT https://api.example.com/leads/7 -H 'Accept: application/json' ` +
          `-H 'Content-Type: application/json' --data '{"name":"Ada"}' -s -L`,
      ),
    ).toEqual({
      method: "PUT",
      url: "https://api.example.com/leads/7",
      headers: { Accept: "application/json" },
      body: { name: "Ada" },
      droppedBody: false,
      credential: null,
    });
  });

  it("posts when it sends data and names no method, and reads --flag=value", () => {
    const parsed = parseCurl(`curl --url=https://api.example.com --json '[1]'`);
    expect(parsed).toMatchObject({ method: "POST", body: [1] });
  });

  it("leaves out a body that is not JSON, and says so", () => {
    const parsed = parseCurl(`curl https://api.example.com -d 'a=1' -d 'b=2'`);
    expect(parsed).toMatchObject({ method: "POST", droppedBody: true });
    expect(parsed).not.toHaveProperty("body");
  });

  it("lifts a bearer token out of the headers", () => {
    const parsed = parseCurl(`curl https://api.example.com -H 'Authorization: Bearer tok-1'`);
    expect(parsed).toMatchObject({ headers: {}, credential: { kind: "bearer", token: "tok-1" } });
  });

  it("lifts basic credentials, from the header or from -u", () => {
    expect(
      parseCurl(`curl https://api.example.com -H 'Authorization: Basic ${btoa("ada:pw")}'`),
    ).toMatchObject({ credential: { kind: "basic", username: "ada", token: "pw" } });
    expect(parseCurl(`curl -u ada:pw https://api.example.com`)).toMatchObject({
      credential: { kind: "basic", username: "ada", token: "pw" },
    });
    expect(parseCurl(`curl -u ada https://api.example.com`)).toMatchObject({
      credential: { kind: "basic", username: "ada", token: "" },
    });
  });

  it("keeps no credential for an Authorization scheme it cannot read", () => {
    for (const value of ["Digest abc", "Basic !!!", `Basic ${btoa("nocolon")}`, "Bearer"]) {
      const parsed = parseCurl(`curl https://api.example.com -H 'Authorization: ${value}'`);
      expect(parsed).toMatchObject({ headers: {}, credential: null });
    }
  });

  it("lifts a key header, and a key parameter out of the URL", () => {
    expect(parseCurl(`curl https://api.example.com -H 'X-Api-Key: k1'`)).toMatchObject({
      headers: {},
      credential: { kind: "header", name: "X-Api-Key", token: "k1" },
    });
    expect(parseCurl(`curl 'https://api.example.com/x?api_key=k2&q=1'`)).toMatchObject({
      url: "https://api.example.com/x?q=1",
      credential: { kind: "query", name: "api_key", token: "k2" },
    });
  });

  it("drops a header that is not a header, and the Content-Length the step works out", () => {
    expect(
      parseCurl(`curl https://api.example.com -H 'nonsense' -H 'Content-Length: 3'`),
    ).toMatchObject({ headers: {} });
  });

  it("says why it cannot read a command", () => {
    expect(parseCurl("wget https://x")).toBe("notCurl");
    expect(parseCurl("curl -s")).toBe("noUrl");
    expect(parseCurl("curl not-a-url")).toBe("noUrl");
    expect(parseCurl("curl -X HEAD https://api.example.com")).toBe("badMethod");
    expect(parseCurl("curl 'https://x")).toBe("unclosedQuote");
  });
});
