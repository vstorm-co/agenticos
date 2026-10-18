// Scenes drawn by hand in the canvas's own vocabulary - the same isometric base,
// face classes and motion - for capabilities added after the canvas export. Kept
// apart from `art.generated.ts`, which the canvas rewrites whole.

export const DRAWN_HUE: Readonly<Record<string, number>> = {
  visuals: 140,
  background_tools: 222,
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

/**
 * Work while tools run: a tool still busy at the back - its spinner turning,
 * `running…` over it - while the agent in front gets on with its list.
 */
const BACKGROUND_TOOLS =
  '<svg viewBox="0 0 240 135" aria-hidden="true" preserveAspectRatio="xMidYMid meet">' +
  '<polygon class="ishb" points="120,46.5 195.7,90.2 120,133.8 44.3,90.2"/>' +
  '<g><polygon class="ict" points="120,33.1 195.7,76.8 120,120.5 44.3,76.8"/>' +
  '<polygon class="icl" points="44.3,82 120,125.7 120,120.5 44.3,76.8"/>' +
  '<polygon class="icr" points="195.7,82 120,125.7 120,120.5 195.7,76.8"/></g>' +
  '<g><polygon class="int" points="120,30 195.7,73.7 120,117.4 44.3,73.7"/>' +
  '<polygon class="inl" points="44.3,76.8 120,120.5 120,117.4 44.3,73.7"/>' +
  '<polygon class="inr" points="195.7,76.8 120,120.5 120,117.4 195.7,73.7"/></g>' +
  '<g transform="matrix(0.9 0.5 -0.9 0.5 120 30)"><path class="igrid2" d="M21 3V81M42 3V81M63 3V81M3 21H81M3 42H81M3 63H81"/></g>' +
  '<g><polygon class="iqt" points="70.8,31.1 90.6,42.5 70.8,54 51,42.5"/>' +
  '<polygon class="iql" points="51,72.4 70.8,83.8 70.8,54 51,42.5"/>' +
  '<polygon class="iqr" points="90.6,72.4 70.8,83.8 70.8,54 90.6,42.5"/></g>' +
  '<g transform="matrix(0.9 0.5 0 1.04 51 42.5)">' +
  '<rect x="3" y="6" width="16" height="3" rx="1.5" class="mu" />' +
  '<g class="breathe" style="animation-delay:-1s"><rect x="3" y="6" width="9" height="3" rx="1.5" class="ac" /></g>' +
  '<rect x="3" y="12" width="12" height="1.6" rx="0.8" class="mu" />' +
  '<rect x="3" y="16" width="8" height="1.6" rx="0.8" class="mu" />' +
  '<circle cx="17" cy="22" r="1.4" class="dk blink" /></g>' +
  '<g transform="matrix(0.9 0.5 -0.9 0.5 70.8 31.1)">' +
  '<circle cx="11" cy="11" r="6" class="igrid" />' +
  '<path class="ln w2 draw" pathLength="100" d="M11 5A6 6 0 1 1 5 11"/></g>' +
  '<g><polygon class="ict" points="117.4,51.7 131.8,60 117.4,68.3 103,60"/>' +
  '<polygon class="icl" points="103,76.6 117.4,85 117.4,68.3 103,60"/>' +
  '<polygon class="icr" points="131.8,76.6 117.4,85 117.4,68.3 131.8,60"/></g>' +
  '<g transform="matrix(0.9 0.5 0 1.04 103 60)">' +
  '<rect x="4.8" y="4.8" width="2.6" height="4.4" rx="1.3" class="dk" />' +
  '<rect x="9.3" y="4.8" width="2.6" height="4.4" rx="1.3" class="dk" /></g>' +
  '<g><polygon class="ict" points="152,60.6 164.6,67.8 143,80.3 130.4,73"/>' +
  '<polygon class="icl" points="130.4,79.3 143,86.6 143,80.3 130.4,73"/>' +
  '<polygon class="icr" points="164.6,74.1 143,86.6 143,80.3 164.6,67.8"/></g>' +
  '<g><polygon class="iqt" points="166.4,60.6 179,67.8 157.4,80.3 144.8,73"/>' +
  '<polygon class="iql" points="144.8,79.3 157.4,86.6 157.4,80.3 144.8,73"/>' +
  '<polygon class="iqr" points="179,74.1 157.4,86.6 157.4,80.3 179,67.8"/></g>' +
  '<g transform="matrix(0.9 0.5 0 1.04 130.4 73)"><path class="ln w2 draw" pathLength="100" style="animation-delay:0s" d="M3 1.5l2.5 2.5 5-5"/></g>' +
  '<g transform="matrix(0.9 0.5 0 1.04 144.8 73)"><path class="ln w2 draw" pathLength="100" style="animation-delay:1.2s" d="M3 1.5l2.5 2.5 5-5"/></g>' +
  '<g class="bob"><g transform="translate(70.8 20)"><rect x="-23" y="-9" width="46" height="16" rx="8" class="pp" />' +
  '<text x="0" y="2.4" class="tx mono s7 mid b" >running…</text></g></g>' +
  "</svg>";

export const DRAWN_ART: Readonly<Record<string, string>> = {
  visuals: VISUALS,
  background_tools: BACKGROUND_TOOLS,
};
