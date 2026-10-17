// Scenes drawn by hand in the canvas's own vocabulary - the same isometric base,
// face classes and motion - for capabilities added after the canvas export. Kept
// apart from `art.generated.ts`, which the canvas rewrites whole.

export const DRAWN_HUE: Readonly<Record<string, number>> = {
  visuals: 140,
};

/** Visuals: a board standing on the base with a small diagram on it, and `draw()` above. */
const VISUALS =
  '<svg viewBox="0 0 240 135" aria-hidden="true" preserveAspectRatio="xMidYMid meet">' +
  '<polygon class="ishb" points="120,46.5 195.7,90.2 120,133.8 44.3,90.2"/>' +
  '<g><polygon class="ict" points="120,33.1 195.7,76.8 120,120.5 44.3,76.8"/>' +
  '<polygon class="icl" points="44.3,82 120,125.7 120,120.5 44.3,76.8"/>' +
  '<polygon class="icr" points="195.7,82 120,125.7 120,120.5 195.7,76.8"/></g>' +
  '<g><polygon class="int" points="120,30 195.7,73.7 120,117.4 44.3,73.7"/>' +
  '<polygon class="inl" points="44.3,76.8 120,120.5 120,117.4 44.3,73.7"/>' +
  '<polygon class="inr" points="195.7,76.8 120,120.5 120,117.4 195.7,73.7"/></g>' +
  '<g transform="matrix(0.9 0.5 -0.9 0.5 120 30)"><path class="igrid2" d="M21 3V81M42 3V81M63 3V81M3 21H81M3 42H81M3 63H81"/></g>' +
  '<polygon class="int" points="91.2,10 148.8,42 146.6,43 89.4,11"/>' +
  '<polygon class="inr" points="148.8,42 148.8,92 146.6,93 146.6,43"/>' +
  '<polygon class="inl" points="89.4,61 146.6,93 146.6,43 89.4,11"/>' +
  '<g transform="matrix(0.9 0.5 0 1 89.4 11)">' +
  '<path class="igrid" d="M20 14H40M14 19L27 33M47 19L36 33"/>' +
  '<g class="breathe" style="animation-delay:0s"><rect class="ict" x="5" y="9" width="16" height="10" rx="2"/></g>' +
  '<g class="breathe" style="animation-delay:-0.6s"><rect class="ict" x="40" y="9" width="17" height="10" rx="2"/></g>' +
  '<g class="breathe" style="animation-delay:-1.2s"><rect class="icr" x="21" y="33" width="21" height="10" rx="2"/></g>' +
  "</g>" +
  '<g class="bob"><g transform="translate(172 30)"><rect x="-19" y="-9" width="38" height="16" rx="8" class="pp" />' +
  '<text x="0" y="2.4" class="tx mono s7 mid b" >draw()</text></g></g>' +
  "</svg>";

export const DRAWN_ART: Readonly<Record<string, string>> = {
  visuals: VISUALS,
};
