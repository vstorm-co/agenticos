import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import {
  DEFAULT_IMAGE_PROMPT,
  DEFAULT_INGESTION_CONFIG,
  ingestionOverride,
  ingestionProblems,
  overrideSize,
  sameIngestion,
  summarizeEmbedding,
  toNumber,
} from "./ingestion-config";
import type { Translate } from "@/lib/agent-step-captions";
import type { IngestionConfig } from "@/types";
import messages from "../../messages/en.json";

/**
 * The real `kb` messages, so a refusal is asserted as the sentence it renders as. Cast
 * because `createTranslator` types its key against the message tree while `Translate`
 * takes the string a module holds.
 */
const t = createTranslator({ locale: "en", messages, namespace: "kb" }) as Translate;

/** The defaults with something moved, without restating the other nine fields. */
function config(changes: Partial<IngestionConfig> = {}): IngestionConfig {
  return { ...DEFAULT_INGESTION_CONFIG, ...changes };
}

describe("ingestionProblems", () => {
  it("accepts the configuration nothing has been done to", () => {
    // The starting point of every form here. If this ever fails, every dialog
    // opens already refusing to submit.
    expect(ingestionProblems(DEFAULT_INGESTION_CONFIG, t)).toEqual({});
  });

  it("refuses an overlap that does not fit inside a chunk, under the overlap", () => {
    // The server's own cross-field rule. It reaches the browser attributed to
    // `ingestion_config` rather than to a field, so answering it locally is the
    // only way it lands on an input somebody can act on.
    const problems = ingestionProblems(config({ chunk_size: 256, chunk_overlap: 300 }), t);

    expect(problems.chunk_overlap).toContain("256");
    expect(problems.chunk_size).toBeUndefined();
  });

  it("refuses an overlap equal to the chunk, which is every chunk repeated whole", () => {
    // The boundary the server draws with `>=`, not `>`.
    expect(ingestionProblems(config({ chunk_size: 512, chunk_overlap: 512 }), t)).toHaveProperty(
      "chunk_overlap",
    );
  });

  it.each([
    ["chunk_size", config({ chunk_size: 63 })],
    ["chunk_size", config({ chunk_size: 8193 })],
    ["chunk_overlap", config({ chunk_overlap: 4097 })],
    ["parse_timeout_seconds", config({ parse_timeout_seconds: 0 })],
    ["parse_timeout_seconds", config({ parse_timeout_seconds: 3601 })],
    ["liteparse_dpi", config({ liteparse_dpi: 71 })],
    ["liteparse_dpi", config({ liteparse_dpi: 601 })],
    ["max_pages", config({ max_pages: 0 })],
    ["max_pages", config({ max_pages: 10001 })],
  ])("refuses a %s outside the bounds the API enforces", (field, value) => {
    expect(ingestionProblems(value, t)).toHaveProperty(field);
  });

  it.each(["en", "pl", "english", "eng+", "ENG", "eng pol", ""])(
    "refuses %p as an OCR language, because Tesseract wants three letters",
    (code) => {
      // The trap is that "pl" looks like the right answer - it is the code used
      // everywhere else in this product for a UI locale. Tesseract has no pack
      // under that name, so the parse would succeed and return nothing.
      expect(ingestionProblems(config({ ocr_language: code }), t)).toHaveProperty("ocr_language");
    },
  );

  it.each(["eng", "pol", "eng+pol", "deu+fra+spa"])("accepts %p", (code) => {
    expect(ingestionProblems(config({ ocr_language: code }), t)).not.toHaveProperty("ocr_language");
  });

  it("treats an emptied number box as unfinished rather than as zero", () => {
    // `Number("")` is 0, which for a chunk size is a plausible-looking value the
    // API refuses. The box says what it is: nothing typed yet.
    expect(ingestionProblems(config({ chunk_size: toNumber("") }), t)).toHaveProperty("chunk_size");
  });

  it("refuses an empty image prompt", () => {
    const problems = ingestionProblems(
      config({ image_description: { ...DEFAULT_INGESTION_CONFIG.image_description, prompt: "" } }),
      t,
    );

    expect(problems).toHaveProperty("prompt");
  });

  it("says nothing about a model profile, which only the server can judge", () => {
    // Whether a profile resolves to a usable key is not knowable here, and a
    // guess would either block a working configuration or promise one that is
    // about to be refused.
    expect(ingestionProblems(config({ describe_images: true }), t)).toEqual({});
  });
});

describe("ingestionOverride", () => {
  it("says nothing when nothing was moved", () => {
    // An empty override still marks a document as overridden if it is sent, so
    // "I opened the dialog and closed it" must produce no departure at all.
    expect(ingestionOverride(DEFAULT_INGESTION_CONFIG, config())).toEqual({});
  });

  it("carries only the fields that differ", () => {
    const override = ingestionOverride(
      DEFAULT_INGESTION_CONFIG,
      config({ pdf_parser: "llamaparse", chunk_size: 1024 }),
    );

    expect(override).toEqual({ pdf_parser: "llamaparse", chunk_size: 1024 });
  });

  it("descends into the image settings rather than replacing them wholesale", () => {
    // Sending the whole object would carry the prompt and the model along with a
    // changed temperature, and each of those is recorded as a departure.
    const override = ingestionOverride(
      DEFAULT_INGESTION_CONFIG,
      config({
        image_description: { ...DEFAULT_INGESTION_CONFIG.image_description, temperature: 0.2 },
      }),
    );

    expect(override).toEqual({ image_description: { temperature: 0.2 } });
  });

  it("carries a different describing model, which is the whole point of the override", () => {
    // An upload of scanned invoices may want a vision model the collection does
    // not use by default.
    const override = ingestionOverride(
      DEFAULT_INGESTION_CONFIG,
      config({
        image_description: {
          ...DEFAULT_INGESTION_CONFIG.image_description,
          model_profile_id: "p-vision",
        },
      }),
    );

    expect(override).toEqual({ image_description: { model_profile_id: "p-vision" } });
  });

  it("carries a temperature put back to unset, because null is a value here", () => {
    // The collection asks for 0.5; this upload asks for the parameter not to be
    // sent at all. Omitting the key would inherit 0.5 and mean the opposite.
    const base = config({
      image_description: { ...DEFAULT_INGESTION_CONFIG.image_description, temperature: 0.5 },
    });

    expect(ingestionOverride(base, config())).toEqual({ image_description: { temperature: null } });
  });

  it("counts every departure, wherever it sits", () => {
    const override = ingestionOverride(
      DEFAULT_INGESTION_CONFIG,
      config({
        ocr: true,
        image_description: {
          ...DEFAULT_INGESTION_CONFIG.image_description,
          prompt: "Read the axis labels.",
          thinking: "high",
        },
      }),
    );

    expect(overrideSize(override)).toBe(3);
  });

  it("counts nothing for an empty one", () => {
    expect(overrideSize({})).toBe(0);
  });
});

describe("sameIngestion", () => {
  it("holds for a copy", () => {
    expect(sameIngestion(DEFAULT_INGESTION_CONFIG, config())).toBe(true);
  });

  it("notices a change buried in the image settings", () => {
    // The create dialog decides whether to send anything at all from this, so a
    // comparison that stopped at the top level would silently drop a chosen
    // prompt.
    const edited = config({
      image_description: {
        ...DEFAULT_INGESTION_CONFIG.image_description,
        prompt: `${DEFAULT_IMAGE_PROMPT} Name every axis.`,
      },
    });

    expect(sameIngestion(DEFAULT_INGESTION_CONFIG, edited)).toBe(false);
  });

  it("distinguishes an unset temperature from zero", () => {
    // The distinction the whole form is built around: one sends no parameter,
    // the other sends `0`, and reasoning models reject the second.
    const zero = config({
      image_description: { ...DEFAULT_INGESTION_CONFIG.image_description, temperature: 0 },
    });

    expect(sameIngestion(DEFAULT_INGESTION_CONFIG, zero)).toBe(false);
  });
});

describe("summarizeEmbedding", () => {
  it("states what a collection was indexed with, not what it is set to", () => {
    // Frozen at creation: two collections on different models are not peers, and
    // this is the line that says which one this is.
    expect(
      summarizeEmbedding({
        embedding_model: "text-embedding-3-large",
        embedding_dim: 3072,
      } as Parameters<typeof summarizeEmbedding>[0]),
    ).toBe("text-embedding-3-large · 3,072 dimensions");
  });
});
