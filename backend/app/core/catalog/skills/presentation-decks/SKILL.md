---
name: presentation-decks
description: How to build a slide deck as a published page with publish_artifact - the 16:9 slide frame, keyboard and touch navigation, speaker notes, charts and print to PDF, from a template that already works.
category: design
---

# Building a deck as a page

A deck is a published page (an App) made of slides. It opens in the browser, needs
no software, can be shared by link, and prints to PDF from the browser. Build it
with `publish_artifact`, after loading `artifact-pages` for the served library and
the house style: a deck uses the same files and the same look.

Decide the story before the slides: load `deck-storyline` if the person has not
given you one. Check the finished deck with `deck-review`.

## Start from the template

Load `templates/deck.html` and replace its slides and its `data` object. Do not
write the frame yourself: it already has the parts that are easy to get wrong.

- **A 1280 x 720 slide, scaled as a whole** to the window, so type and spacing keep
  their proportions on a laptop, a projector and a phone.
- **Navigation**: arrow keys, Page Up and Down, space, Home and End, a swipe, a click
  on the slide. The address carries the slide number (`#3`), so a slide can be linked.
- **Speaker notes**: each slide may hold `<aside class="notes">`; the `n` key shows them.
- **Print**: the browser's print dialog gives one slide per page at 16:9 (save as PDF).
- **Progress**: a thin bar and `3 / 9` in the corner.

## The slides

Use the `ao-` components inside slides - `.ao-stat`, `.ao-card`, `.ao-grid-3`,
`.ao-table`, `.ao-callout` - and the house style from `artifact-pages`: graphite, no
accent colour, green and red only for better and worse, icons not emoji.

- **Big type.** The template's sizes are for a room: a title of 44 px, body text of
  at least 28 px, a table at 24 px. If it does not fit at that size, it is two slides.
- **One message per slide**, and the slide's title is that message as a sentence
  (`Fabrikam delivered 48% of its orders late`), not its topic (`Delivery`).
- **At most six lines of text** and no paragraphs. A slide that needs more is a
  document: put it in the notes or in a page.
- **A chart is one chart.** Set `Chart.defaults.font.size = 18` before creating it,
  create it with `AO.chart`, label the axes the reader needs and nothing else, and
  say in the title what the chart shows. Never two charts on one slide.
- **Numbers**: `AO.format` writes them the way the page's language does; set
  `<html lang="pl">` for a Polish audience, and write the slides in that language.
- **Images** go in as `data:` URIs or `{{image:NAME}}`; the page has no network.
  A photo carries its credit in small text on the slide.

## Structure

A deck of five to twelve slides is read in ten to twenty minutes. The usual order:
the answer (title slide or the next one), why, the evidence in two to five slides,
what you recommend or need decided. Put the decision last and say it in words.

## Changing a deck later

Publish again under the same `name`, so the link keeps working and the earlier
version stays in its history; for a small change use `edits` rather than the whole
deck. Keep the data in one `const data`
at the top of the script, as numbers rather than formatted strings.

## Never

Write the frame again, put text smaller than 24 px on a slide, set a slide's
background to a colour of your own, fill a slide to its edges, read the slide
aloud in the notes (notes say what the slide does not), or use emoji unless the
person asked for them.
