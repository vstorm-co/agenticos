import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import {
  DEFAULT_IMAGE_PROMPT,
  DEFAULT_INGESTION_CONFIG,
  ingestionOverride,
  ingestionProblems,
  overrideSize,
  PDF_PARSERS,
  sameIngestion,
  settleHiddenFields,
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

describe("settleHiddenFields", () => {
  const scanning = config({ pdf_parser: "liteparse", ocr: true });

  it("puts a refused OCR pair back to the defaults when OCR is turned off", () => {
    // The field showing the error goes away with OCR, so keeping the value would
    // disable submit with nothing on screen to fix (#1930).
    const settled = settleHiddenFields(
      { ...scanning, ocr: false, ocr_language: "pl", liteparse_dpi: 9000 },
      t,
    );

    expect(settled.ocr_language).toBe(DEFAULT_INGESTION_CONFIG.ocr_language);
    expect(settled.liteparse_dpi).toBe(DEFAULT_INGESTION_CONFIG.liteparse_dpi);
    expect(ingestionProblems(settled, t)).toEqual({});
  });

  it("keeps a valid hidden value, so switching back finds what was set", () => {
    const settled = settleHiddenFields({ ...scanning, ocr: false, ocr_language: "pol" }, t);

    expect(settled.ocr_language).toBe("pol");
  });

  it("leaves a refused value alone while its field is on screen", () => {
    // Somebody halfway through typing is shown the problem, not overruled.
    const settled = settleHiddenFields({ ...scanning, ocr_language: "pl" }, t);

    expect(settled.ocr_language).toBe("pl");
  });

  it("settles LiteParse's own limits when another parser is chosen", () => {
    const settled = settleHiddenFields(
      config({ pdf_parser: "pymupdf", max_pages: 0, parse_timeout_seconds: 0 }),
      t,
    );

    expect(settled.max_pages).toBe(DEFAULT_INGESTION_CONFIG.max_pages);
    expect(settled.parse_timeout_seconds).toBe(DEFAULT_INGESTION_CONFIG.parse_timeout_seconds);
  });

  it("settles an emptied image prompt once images are no longer described", () => {
    const settled = settleHiddenFields(
      config({
        describe_images: false,
        image_description: { ...DEFAULT_INGESTION_CONFIG.image_description, prompt: "" },
      }),
      t,
    );

    expect(settled.image_description.prompt).toBe(DEFAULT_IMAGE_PROMPT);
  });

  it("returns the same object when nothing hidden is refused", () => {
    expect(settleHiddenFields(DEFAULT_INGESTION_CONFIG, t)).toBe(DEFAULT_INGESTION_CONFIG);
  });
});

describe("Docling options", () => {
  it("starts with the API's defaults, so an old collection and a new one agree", () => {
    expect(DEFAULT_INGESTION_CONFIG).toMatchObject({
      docling_connection_id: null,
      docling_ocr_languages: [],
      docling_ocr_preset: "auto",
      docling_table_mode: "accurate",
    });
  });

  it("offers Docling beside the other three parsers", () => {
    expect(PDF_PARSERS.map((choice) => choice.value)).toEqual([
      "pymupdf",
      "llamaparse",
      "liteparse",
      "docling",
    ]);
  });

  it("refuses a language that is not two letters, and more than eight", () => {
    expect(ingestionProblems(config({ docling_ocr_languages: ["de", "en"] }), t)).toEqual({});
    expect(ingestionProblems(config({ docling_ocr_languages: ["deu"] }), t)).toHaveProperty(
      "docling_ocr_languages",
    );
    expect(
      ingestionProblems(
        config({ docling_ocr_languages: ["aa", "bb", "cc", "dd", "ee", "ff", "gg", "hh", "ii"] }),
        t,
      ),
    ).toHaveProperty("docling_ocr_languages");
  });

  it("refuses a preset the API would", () => {
    expect(ingestionProblems(config({ docling_ocr_preset: "Rapid OCR" }), t)).toHaveProperty(
      "docling_ocr_preset",
    );
    expect(ingestionProblems(config({ docling_ocr_preset: "" }), t)).toHaveProperty(
      "docling_ocr_preset",
    );
    expect(ingestionProblems(config({ docling_ocr_preset: "rapidocr" }), t)).toEqual({});
  });

  it("settles a refused Docling option when another parser is chosen", () => {
    const settled = settleHiddenFields(
      config({
        pdf_parser: "pymupdf",
        docling_ocr_preset: "Not Valid",
        docling_ocr_languages: ["x"],
      }),
      t,
    );

    expect(settled.docling_ocr_preset).toBe("auto");
    expect(settled.docling_ocr_languages).toEqual([]);
  });

  it("settles LiteParse's limits only when neither LiteParse nor Docling is chosen", () => {
    const docling = config({ pdf_parser: "docling", max_pages: 0 });
    expect(settleHiddenFields(docling, t)).toBe(docling);
    expect(settleHiddenFields(config({ pdf_parser: "pymupdf", max_pages: 0 }), t).max_pages).toBe(
      1000,
    );
  });

  it("carries a changed language list and table mode in an override, not the connection", () => {
    const base = config({ pdf_parser: "docling", docling_connection_id: "c-1" });
    const override = ingestionOverride(base, {
      ...base,
      docling_ocr_languages: ["de"],
      docling_table_mode: "fast",
    });

    expect(override).toEqual({ docling_ocr_languages: ["de"], docling_table_mode: "fast" });
  });

  it("compares language lists by content, not by identity", () => {
    const a = config({ docling_ocr_languages: ["de", "en"] });
    expect(sameIngestion(a, config({ docling_ocr_languages: ["de", "en"] }))).toBe(true);
    expect(sameIngestion(a, config({ docling_ocr_languages: ["en", "de"] }))).toBe(false);
    expect(ingestionOverride(a, config({ docling_ocr_languages: ["de", "en"] }))).toEqual({});
  });
});

describe("the OCR switch under a parser that ignores it", () => {
  it("is turned off when LlamaParse is chosen", () => {
    const settled = settleHiddenFields(
      { ...DEFAULT_INGESTION_CONFIG, pdf_parser: "llamaparse", ocr: true },
      t,
    );
    expect(settled.ocr).toBe(false);
  });

  it("is kept where the parser reads it", () => {
    for (const parser of ["pymupdf", "liteparse", "docling"] as const) {
      const settled = settleHiddenFields(
        { ...DEFAULT_INGESTION_CONFIG, pdf_parser: parser, ocr: true },
        t,
      );
      expect(settled.ocr).toBe(true);
    }
  });
});
