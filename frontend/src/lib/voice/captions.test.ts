import { describe, expect, it } from "vitest";

import { applyCaption, applySavedTurn, CAPTION_LIMIT, captionKey, type Caption } from "./captions";

type Frame = Parameters<typeof applyCaption>[1];

function frame(fields: Partial<Frame>): Frame {
  return { type: "caption", role: "user", turn_id: "t1", part: 0, ...fields };
}

describe("captions", () => {
  it("builds a line word by word and replaces it with the final text", () => {
    let captions = applyCaption([], frame({ delta: " Weather" }));
    captions = applyCaption(captions, frame({ delta: " in Warsaw" }));
    expect(captions).toEqual([
      { turnId: "t1", part: 0, role: "user", text: " Weather in Warsaw", final: false },
    ]);
    captions = applyCaption(captions, frame({ final: "Weather in Warsaw?" }));
    expect(captions[0]).toEqual({
      turnId: "t1",
      part: 0,
      role: "user",
      text: "Weather in Warsaw?",
      final: true,
    });
  });

  it("replaces a line with the screened text so far, for an agent behind an output guardrail", () => {
    let captions = applyCaption([], frame({ role: "assistant", text: "It is eight degrees." }));
    expect(captions[0]?.text).toBe("It is eight degrees.");
    captions = applyCaption(
      captions,
      frame({ role: "assistant", text: "It is eight degrees. Take a coat." }),
    );
    expect(captions).toHaveLength(1);
    expect(captions[0]).toMatchObject({ text: "It is eight degrees. Take a coat.", final: false });
  });

  it("keeps each part of one response on its own line", () => {
    let captions = applyCaption(
      [],
      frame({ role: "assistant", turn_id: "a1", delta: "Let me check." }),
    );
    captions = applyCaption(
      captions,
      frame({ role: "assistant", turn_id: "a1", final: "Let me check." }),
    );
    captions = applyCaption(
      captions,
      frame({ role: "assistant", turn_id: "a1", part: 1, delta: "Eight" }),
    );
    captions = applyCaption(
      captions,
      frame({ role: "assistant", turn_id: "a1", part: 1, final: "Eight degrees." }),
    );
    expect(captions.map((line) => [captionKey(line), line.text, line.final])).toEqual([
      ["a1:0", "Let me check.", true],
      ["a1:1", "Eight degrees.", true],
    ]);
  });

  it("keeps both speakers in order and forgets the oldest past the limit", () => {
    let captions: Caption[] = [];
    for (let i = 0; i < CAPTION_LIMIT + 5; i++) {
      captions = applyCaption(
        captions,
        frame({ role: i % 2 ? "assistant" : "user", turn_id: `t${i}`, final: `line ${i}` }),
      );
    }
    expect(captions).toHaveLength(CAPTION_LIMIT);
    expect(captions[0]?.turnId).toBe("t5");
  });

  it("ignores a delta or a screened update for a line that is already final", () => {
    const final = applyCaption([], frame({ role: "assistant", final: "Done." }));
    expect(applyCaption(final, frame({ role: "assistant", delta: " late" }))).toEqual(final);
    expect(applyCaption(final, frame({ role: "assistant", text: "late" }))).toEqual(final);
  });

  it("treats a frame with neither words nor a final as an empty delta", () => {
    expect(applyCaption([], frame({}))).toEqual([
      { turnId: "t1", part: 0, role: "user", text: "", final: false },
    ]);
  });

  it("finishes an earlier line while the other speaker's line goes on", () => {
    let captions = applyCaption([], frame({ delta: "Hi" }));
    captions = applyCaption(captions, frame({ role: "assistant", turn_id: "t2", delta: "Hello" }));
    captions = applyCaption(captions, frame({ final: "Hi." }));
    expect(captions.map((line) => [line.turnId, line.text, line.final])).toEqual([
      ["t1", "Hi.", true],
      ["t2", "Hello", false],
    ]);
  });
});

describe("a saved turn", () => {
  const saved = (turn_id: string | null, content: string) => ({
    id: "m1",
    role: "assistant",
    content,
    interrupted: false,
    turn_id,
  });

  it("takes the place of every caption line of its turn, where the first stood", () => {
    let captions = applyCaption([], frame({ turn_id: "u1", final: "Weather?" }));
    captions = applyCaption(
      captions,
      frame({ role: "assistant", turn_id: "a1", final: "Let me check." }),
    );
    captions = applyCaption(
      captions,
      frame({ role: "assistant", turn_id: "a1", part: 1, delta: "Eight deg" }),
    );
    captions = applyCaption(captions, frame({ turn_id: "u2", delta: "Thanks" }));
    const after = applySavedTurn(captions, saved("a1", "Let me check. Eight degr"));
    expect(after.map((line) => [captionKey(line), line.text, line.final])).toEqual([
      ["u1:0", "Weather?", true],
      ["a1:0", "Let me check. Eight degr", true],
      ["u2:0", "Thanks", false],
    ]);
  });

  it("drops the lines of a turn saved with no words, and leaves a turn it never showed alone", () => {
    const captions = applyCaption([], frame({ role: "assistant", turn_id: "a1", delta: "x" }));
    expect(applySavedTurn(captions, saved("a1", ""))).toEqual([]);
    expect(applySavedTurn(captions, saved("a9", "y"))).toEqual(captions);
    expect(applySavedTurn(captions, saved(null, "y"))).toEqual(captions);
  });
});
