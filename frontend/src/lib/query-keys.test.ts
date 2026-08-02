import { describe, expect, it } from "vitest";

import { qk } from "./query-keys";

/**
 * The cache's vocabulary.
 *
 * Two rules, and both are invisible until something goes stale: a key is
 * hierarchical, so a broader prefix invalidates everything beneath it, and two
 * keys that should differ must actually differ. A detail key that collides with
 * its list renders one agent's spec for another; a list key that ignores its
 * filter serves the unarchived list to a page that asked for archived rows.
 *
 * Asserted structurally rather than value-by-value: the invariant is the shape,
 * and a table of two hundred literals would need editing every time a namespace
 * is added without ever failing for a reason worth knowing.
 */

/** Every factory in the tree, with the arguments its arity implies. */
function keys(): [string, readonly unknown[]][] {
  const out: [string, readonly unknown[]][] = [];
  const walk = (node: unknown, path: string) => {
    if (typeof node === "function") {
      const args = Array.from({ length: node.length }, (_, index) => `arg${index}`);
      out.push([path, (node as (...a: string[]) => readonly unknown[])(...args)]);
      return;
    }
    if (node && typeof node === "object") {
      for (const [name, child] of Object.entries(node))
        walk(child, path ? `${path}.${name}` : name);
    }
  };
  walk(qk, "");
  return out;
}

describe("the query key factory", () => {
  it("has a factory for every entry, and every one answers with an array", () => {
    const all = keys();

    expect(all.length).toBeGreaterThan(40);
    for (const [path, key] of all) {
      expect(Array.isArray(key), path).toBe(true);
      expect(key.length, path).toBeGreaterThan(0);
    }
  });

  it("gives every key a string namespace to invalidate by", () => {
    for (const [path, key] of keys()) {
      expect(typeof key[0], path).toBe("string");
    }
  });

  it("hands no two entries the same key", () => {
    // A collision serves one query's data to another, which reads as a caching
    // bug somewhere else entirely.
    const seen = new Map<string, string>();

    for (const [path, key] of keys()) {
      const serialized = JSON.stringify(key);
      expect(seen.get(serialized), `${path} collides with ${seen.get(serialized)}`).toBeUndefined();
      seen.set(serialized, path);
    }
  });

  it("nests a detail key under the list it belongs to", () => {
    // Which is what lets `invalidateQueries({ queryKey: qk.agents.all() })` reach
    // a single agent's spec as well as the listing.
    expect(qk.agents.detail("a1")[0]).toBe(qk.agents.all()[0]);
    expect(qk.agents.version("a1", "v1").slice(0, 2)).toEqual(qk.agents.detail("a1"));
  });

  it("keeps the archived filter in the agents list key", () => {
    // The two lists are different rows; one key would serve whichever arrived
    // first to both pages.
    expect(qk.agents.list(true)).not.toEqual(qk.agents.list(false));
    expect(qk.agents.list()).toEqual(qk.agents.list(false));
  });

  it("keys sharing by resource type as well as by id", () => {
    // An agent and a skill can hold the same id, and their sharing is not the
    // same row.
    expect(qk.sharing.detail("agent", "x")).not.toEqual(qk.sharing.detail("skill", "x"));
  });

  it("names the whole-organization run list rather than keying it on undefined", () => {
    // `["runs","list",undefined]` and `["runs","list"]` are different keys to
    // React Query and the same list to a reader.
    expect(qk.runs.list()).toEqual(["runs", "list", "all"]);
    expect(qk.runs.list("a1")).toEqual(["runs", "list", "a1"]);
  });

  it("keys a paged list by its window", () => {
    expect(qk.conversationShares.sharedWithMe(0, 20)).not.toEqual(
      qk.conversationShares.sharedWithMe(20, 20),
    );
  });

  it("separates one tenant's cache from another's", () => {
    // Two organizations hold collections of the same name, and their documents
    // are not the same rows. Sharing a key means the second tenant is served
    // the first one's names out of the cache while its own request is still in
    // flight - a leak that looks like a rendering delay.
    expect(qk.rag.collections("org-a")).not.toEqual(qk.rag.collections("org-b"));
    expect(qk.rag.documents("org-a", "handbook")).not.toEqual(
      qk.rag.documents("org-b", "handbook"),
    );
    expect(qk.integrations.reusable("org-a")).not.toEqual(qk.integrations.reusable("org-b"));
  });
});
