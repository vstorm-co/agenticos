---
name: Print file validation
description: Check an artwork file against the press requirements and say exactly what to fix.
category: operations
---

# Validating artwork for print

A rejection that says "file not suitable" produces another bad file. Say the
number and the target.

## Check, in this order

- **Resolution** at final size — report the effective DPI, not the pixel count.
- **Colour mode** and profile.
- **Bleed and safe area** — how many millimetres present against required.
- **Fonts** — outlined or embedded.
- **Transparency and overprint** where the press cannot hold them.
- **Dimensions and orientation** against the ordered product.

## Report like this

> Requires 300 dpi at 40 × 50 cm. Supplied file is 96 dpi at that size
> (1512 × 1890 px). Send at least 4724 × 5906 px, or a vector file.

Number found, number needed, and the fix. Every time.

## Judgement calls

Anything between the reject threshold and the warning threshold is offered to
the customer with the trade-off stated — "this will print, and fine detail will
soften".

## Never

Approve a file that fails a hard requirement because the customer is in a hurry,
or silently rescale.
