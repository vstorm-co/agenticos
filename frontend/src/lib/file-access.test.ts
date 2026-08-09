import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { openFileInNewTab, saveBlob, type FileAccess } from "./file-access";

let created: string[];
let revoked: string[];

beforeEach(() => {
  created = [];
  revoked = [];
  // jsdom has neither, and what is under test is making one and releasing it.
  Object.assign(URL, {
    createObjectURL: () => {
      const url = `blob:${created.length}`;
      created.push(url);
      return url;
    },
    revokeObjectURL: (url: string) => revoked.push(url),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function access(overrides: Partial<FileAccess> = {}): FileAccess {
  return {
    textKey: ["t"],
    bytesKey: ["b"],
    readText: () => Promise.resolve({ content: "", truncated: false }),
    readBytes: () => Promise.resolve(new Blob(["%PDF-"])),
    download: () => Promise.resolve(),
    ...overrides,
  };
}

/**
 * The file in a tab of its own, for every origin at once.
 *
 * Generic because a blob is: the bytes are already fetched with the organization
 * header this page is scoped to, so the tab shows the same tenant's file. A bare URL
 * would arrive without that header and be answered for the caller's personal
 * organization instead.
 */
describe("opening a file in a new tab", () => {
  it("opens the bytes it fetched, in a tab that cannot reach back", () => {
    // `noopener` because the blob is rendered by the browser and the opened context
    // has no business touching this one.
    const open = vi.fn();
    vi.stubGlobal("open", open);

    return openFileInNewTab(access()).then(() => {
      expect(open).toHaveBeenCalledWith("blob:0", "_blank", "noopener,noreferrer");
    });
  });

  it("holds the URL open for a minute, then releases it", async () => {
    // Revoking straight away shows the new tab an error; never revoking holds the
    // whole file in memory for the life of the page. The delay is the behaviour, so
    // the timer has to be run to see it.
    vi.useFakeTimers();
    vi.stubGlobal("open", vi.fn());

    await openFileInNewTab(access());

    expect(revoked).toEqual([]);
    vi.advanceTimersByTime(60_000);
    expect(revoked).toEqual(created);
  });

  it("does not swallow a refusal", async () => {
    vi.stubGlobal("open", vi.fn());

    await expect(
      openFileInNewTab(access({ readBytes: () => Promise.reject(new Error("gone")) })),
    ).rejects.toThrow("gone");
  });
});

describe("handing a blob to the browser as a download", () => {
  it("names the file, because an id in a downloads folder is unfindable", () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    saveBlob(new Blob(["a,b"]), "report.csv");

    expect((click.mock.instances[0] as HTMLAnchorElement).download).toBe("report.csv");
    click.mockRestore();
  });

  it("keeps the URL alive until the browser has read it", () => {
    // Firefox and Safari read a blob URL after the click handler returns, so revoking
    // synchronously cancels the download there - and Chrome tolerates it, which is
    // exactly how this ships broken for half the users.
    vi.useFakeTimers();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    saveBlob(new Blob(["a,b"]), "report.csv");

    expect(revoked).toEqual([]);
    vi.advanceTimersByTime(0);
    expect(revoked).toEqual(created);
    click.mockRestore();
  });
});
