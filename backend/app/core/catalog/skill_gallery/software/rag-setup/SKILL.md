---
name: rag-setup
description: Choose how documents become a knowledge base - parser, chunking, retrieval and reranking - for the documents at hand.
category: engineering
---

# Setting up a knowledge base

Start from the documents, not from the settings.

## Ask what they are

- **Plain prose** (policies, articles, manuals): the defaults are right.
- **Scanned PDFs or images**: they need OCR; pick a parser that reads images.
- **Tables and spreadsheets** (price lists, specs): larger chunks, so a row is
  not split from its header; a parser that keeps table structure.
- **Short Q&A pairs** (FAQ): small chunks, one question each.
- **Code or logs**: chunk on structure, not on characters.

## The settings, in plain words

- **Chunk size** - how much text is one searchable piece. Bigger keeps context,
  smaller finds precise facts. Default first; change only with a reason.
- **Top-k** - how many pieces reach the agent per question. 4-8 is typical; more
  costs tokens and adds noise.
- **Reranking** - a second, smarter pass that reorders what was found. Turn it on
  when answers cite the wrong passage.
- **Hybrid search** - words and meaning together; helps with product codes and
  names.

## Check it

After ingesting, search for three questions a real user would ask. If the right
passage is not in the results, change one setting at a time.
