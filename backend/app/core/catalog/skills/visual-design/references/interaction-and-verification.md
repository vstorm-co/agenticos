# Interaction that teaches

Choose a small number of controls that reveal the relationship. Each needs a visible label, a meaningful range and a useful default. Put units next to numeric inputs. Validate missing, non-finite and out-of-range values before updating a calculation; do not silently change a blank value into a confident result.

## Keep cause and effect together

A slider should update the relevant geometry and the numeric consequence. Let a reader compare the baseline and changed state; show the equation or assumption when it is part of the lesson. Reset restores all inputs, selection and playback state. A randomized scene should keep or expose its seed so the same settings can be revisited.

For a chart, labels and a data table give access beyond pointer hover. For a diagram, keyboard-accessible selection can show detail without moving the whole scene. Avoid adding a control whose value changes nothing visible.

## Motion and performance

Start with a useful still composition. Continuous animation needs pause/stop; reduced-motion preference should keep a complete static view, not hide the result. Update from input events or a bounded animation loop, and cancel work when it ends. Cap particles, geometry and device-pixel ratio. Resize from the available container instead of assuming a desktop canvas size.

Use SVG when nodes, labels and relationships should remain crisp and inspectable. Use Canvas when many marks make a DOM representation expensive, and keep an accessible description and relevant values outside the bitmap. A camera is an exploration aid, not a reason to omit an explanation.

## Isolated execution

Use the active tool's accepted kind and local paths. Visuals and Apps do not use interchangeable helper versions. Images must use the drawing tool's image admission; a remote `src` is not a working substitute. Explicitly check an unavailable library/WebGL context and provide a useful explanation or supported fallback. Never conceal a script exception with a fake successful result.

## Rendered checks

- The primary relationship and initial state are understandable before interaction.
- Every input, button, selection and reset works with a keyboard and a pointer/touch input.
- Input limits and missing/invalid values yield an honest result or clear correction.
- Phone and desktop preserve labels, legibility and the action/result relationship; no accidental sideways page scroll.
- A still/reduced-motion result is complete; pause actually stops animation and reset restores it predictably.
- SVG/Canvas geometry and scales match the stated calculation. Text alternatives carry the essential values.
- There are no unexpected network requests, missing local assets or console exceptions.
- The real `draw` surface renders successfully. An HTML file preview alone does not verify the served frame, image permissions or the chat's result.

Keep the initial skill and tool result compact. Read a matching example/reference when needed and edit an existing visual by a targeted revision rather than repeatedly returning its full source.
