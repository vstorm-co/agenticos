# Set up a knowledge base

Getting an agent to answer from your own documents, end to end. About twenty
minutes, no terminal, and one decision on the way that cannot be undone.

[File processing](../file-processing.md) explains the pipeline; this is the
recipe.

## 1. Create the collection

**Knowledge → New**. Give it a name a person would recognise — it is what
somebody picks from a list later — and a scope, which decides whether it is
yours or the organization's.

!!! danger "The embedding model is frozen at creation"

    It is the one choice on this page you cannot change afterwards. The vector
    column is created at that model's width, and two models of equal width still
    write into *different* spaces — so search would go on comparing vectors that
    do not mean the same thing.

    Changing your mind later means creating a new collection and re-ingesting
    everything. Leave it at the deployment default unless you have a reason, and
    if you have one, see [Choosing a model](../choosing-models.md#embeddings-are-a-separate-permanent-choice).

## 2. Decide how documents are read

Every collection carries its own ingestion settings, and every upload can
override them. The defaults are sensible; these are the three worth a thought.

**Which parser reads a PDF.**

| | What it is | Pick it when |
|---|---|---|
| `pymupdf` | Local, fast, free — and the only one that extracts embedded images for description | Text-first documents. Start here |
| `liteparse` | Local, layout-aware, keeps tables as ASCII grids rather than flattening them | Documents whose meaning is in their tables |
| `llamaparse` | A cloud service, billed per page, returns markdown | Scanned or awkward documents the local two mangle — and you accept the pages leaving |

**Whether to OCR.** On for scans and photographs of documents, off otherwise. It
is slower and it invents characters on clean text.

**How pages are cut into chunks.** `recursive` splits on structure and is the
right default; `markdown` follows headings, which is better when your documents
genuinely have them; `fixed` is a blunt character count, for when the other two
produce nonsense.

!!! tip "Change one thing at a time"

    These settings interact. If retrieval is poor, change the parser *or* the
    chunking, re-ingest one document, and ask the same question again.

## 3. Put documents in

Two ways, and you can use both in one collection.

**Upload** files directly — the parser you chose reads them, chunks them, embeds
them, and the document shows as `processing` until that finishes.

**Sync a source** — a Google Drive folder or an S3 bucket, re-read on a
schedule, so the collection follows the folder instead of a copy of it. See
[Configure sync sources](configure-sync-sources.md).

!!! warning "If ingestion fails on a fresh install, check the database image"

    The store issues `CREATE EXTENSION IF NOT EXISTS vector` the first time a
    collection is written to, and stock Postgres answers *extension "vector" is
    not available* — a 500 before any row is committed. The image must be
    `pgvector/pgvector:pg16`.

## 4. Give it to an agent

In the Builder, on the agent:

1. Switch on the **Knowledge search** capability.
2. Bind the collection — an agent searches the collections you name and nothing
   else.
3. Set `default_top_k`, the number of chunks a search returns.

**Start at three.** Eight chunks where three would do is the most common quiet
overspend in this product: retrieved text is read on the turn it arrives, on
every turn it is carried, and it is usually the largest thing in the prompt.

Then say so in the instructions. Retrieval puts the text in front of the model;
the instructions decide what it does with it:

```
Answer from the knowledge collection and cite the document you used.
If the collection does not cover it, say so rather than guessing.
```

That second sentence is what turns a confident invention into "I do not have
that" — and it is worth testing deliberately, by asking something you know is
not in the documents.

## 5. Test it

Publish, open the agent's **Test** tab, and ask three questions:

| Ask | You are checking |
|---|---|
| Something clearly in the documents | That retrieval works at all, and that the answer carries a citation |
| Something clearly *not* in them | That it refuses instead of inventing |
| Something on the edge — a detail in a table, or in a scan | Whether the parser actually read that part |

The third is the one that finds real problems, and it is why the parser choice
in step 2 is worth revisiting rather than trusting.

## When it cannot find something that is definitely there

Work down this list; it is roughly in order of how often each is the cause.

1. **Is the document `processing` or failed?** A failed document's error is on
   the document itself and says which stage gave up.
2. **Is the collection bound to *this* agent?** Binding is per agent, and a
   published version carries the bindings it had when it was published.
3. **Did the parser read that part?** Open the document and look at the extracted
   text. A table flattened into prose or a scan with no OCR is invisible to
   search, however clearly you can see it.
4. **Is `default_top_k` too small?** Three is right for a focused corpus and too
   few for a broad one.
5. **Is the page actually empty, or did the request fail?** Both render the same
   "nothing here". Check the network tab before concluding anything.

## Recap

- The **embedding model is frozen at creation**. It is the only irreversible
  choice here.
- **`pymupdf` first**, `liteparse` for table-heavy documents, `llamaparse` when
  the pages may leave and the others cannot cope.
- **Start `default_top_k` at three** and raise it only if answers are actually
  missing context.
- Instructions have to say **"say so rather than guessing"** — retrieval alone
  does not stop invention.
- Test with something that is **not** in the documents, and something buried in
  a table.

[The pipeline in detail →](../file-processing.md) ·
[Syncing a folder →](configure-sync-sources.md)
