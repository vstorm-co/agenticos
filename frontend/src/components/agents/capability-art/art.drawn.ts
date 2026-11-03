// Scenes drawn by hand in the canvas's own vocabulary - the same isometric base,
// face classes and motion - for capabilities added after the canvas export. Kept
// apart from `art.generated.ts`, which the canvas rewrites whole.

export const DRAWN_HUE: Readonly<Record<string, number>> = {
  visuals: 140,
  background_tools: 222,
  virtual_tables: 200,
  workflows: 270,
  text_to_speech: 28,
  computer_use: 200,
  video_generation: 300,
  follow_ups: 172,
  monitor: 55,
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
 * Watch a command: a log window standing on the base, its lines arriving one by one,
 * with one line lit where the agent was told about it.
 */
const MONITOR =
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
  '<rect x="6" y="8" width="30" height="2.4" rx="1.2" class="mu" />' +
  '<rect x="6" y="15" width="40" height="2.4" rx="1.2" class="mu" />' +
  '<g class="breathe" style="animation-delay:-0.8s"><rect x="6" y="22" width="34" height="2.4" rx="1.2" class="ac" /></g>' +
  '<rect x="6" y="29" width="24" height="2.4" rx="1.2" class="mu" />' +
  '<circle cx="9" cy="39" r="1.6" class="dk blink" /></g>' +
  '<g class="bob"><g transform="translate(176 32)"><rect x="-21" y="-9" width="42" height="16" rx="8" class="pp" />' +
  '<text x="0" y="2.4" class="tx mono s7 mid b" >error</text></g></g>' +
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

/** Computer use: a screen standing on the base, a window on it and a pointer clicking, `click()` above. */
const COMPUTER_USE =
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
  '<rect x="6" y="6" width="40" height="28" rx="2" class="ict" />' +
  '<rect x="6" y="6" width="40" height="5" rx="2" class="mu" />' +
  '<rect x="10" y="15" width="22" height="2" rx="1" class="mu" />' +
  '<rect x="10" y="20" width="16" height="2" rx="1" class="mu" />' +
  '<g class="breathe" style="animation-delay:-0.6s"><rect x="30" y="26" width="12" height="5" rx="1.5" class="ac" /></g>' +
  '<g class="bob"><path class="dk" d="M37 27l0 9 2.4-2.3 1.8 3.8 1.6-0.8-1.8-3.7 3.3-0.2z"/></g>' +
  "</g>" +
  '<g class="bob"><g transform="translate(172 30)"><rect x="-19" y="-9" width="38" height="16" rx="8" class="pp" />' +
  '<text x="0" y="2.4" class="tx mono s7 mid b" >click()</text></g></g>' +
  "</svg>";

/** Text to speech: a speaker standing on the base, sound leaving it, and `speak()` above. */
const TEXT_TO_SPEECH =
  '<svg viewBox="0 0 240 135" aria-hidden="true" preserveAspectRatio="xMidYMid meet">' +
  '<polygon class="ishb" points="120,46.5 195.7,90.2 120,133.8 44.3,90.2"/>' +
  '<g><polygon class="ict" points="120,33.1 195.7,76.8 120,120.5 44.3,76.8"/>' +
  '<polygon class="icl" points="44.3,82 120,125.7 120,120.5 44.3,76.8"/>' +
  '<polygon class="icr" points="195.7,82 120,125.7 120,120.5 195.7,76.8"/></g>' +
  '<g><polygon class="int" points="120,30 195.7,73.7 120,117.4 44.3,73.7"/>' +
  '<polygon class="inl" points="44.3,76.8 120,120.5 120,117.4 44.3,73.7"/>' +
  '<polygon class="inr" points="195.7,76.8 120,120.5 120,117.4 195.7,73.7"/></g>' +
  '<g transform="matrix(0.9 0.5 -0.9 0.5 120 30)"><path class="igrid2" d="M21 3V81M42 3V81M63 3V81M3 21H81M3 42H81M3 63H81"/></g>' +
  '<g><polygon class="ict" points="104,36 130,51 104,66 78,51"/>' +
  '<polygon class="icl" points="78,81 104,96 104,66 78,51"/>' +
  '<polygon class="icr" points="130,81 104,96 104,66 130,51"/></g>' +
  '<g transform="matrix(0.866 -0.5 0 1 104 66)">' +
  '<circle cx="15" cy="15" r="8" class="dk" />' +
  '<g class="breathe"><circle cx="15" cy="15" r="3.2" class="ac" /></g></g>' +
  '<path class="ln w2 draw" pathLength="100" style="animation-delay:0s" d="M140 58q7 11 0 22"/>' +
  '<path class="ln w2 draw" pathLength="100" style="animation-delay:0.4s" d="M150 52q11 17 0 34"/>' +
  '<path class="ln w2 draw" pathLength="100" style="animation-delay:0.8s" d="M160 46q15 23 0 46"/>' +
  '<g class="bob"><g transform="translate(166 26)"><rect x="-21" y="-9" width="42" height="16" rx="8" class="pp" />' +
  '<text x="0" y="2.4" class="tx mono s7 mid b" >speak()</text></g></g>' +
  "</svg>";

/** Video generation: a screen standing on the base, a clip playing on it, and `action()` above. */
const VIDEO_GENERATION =
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
  '<rect class="dk" x="4" y="6" width="56" height="34" rx="3"/>' +
  '<g class="breathe"><path class="ac" d="M27 15L39 23L27 31Z"/></g>' +
  '<rect class="mu" x="4" y="44" width="56" height="3" rx="1.5"/>' +
  '<g class="breathe" style="animation-delay:-0.8s"><rect class="ac" x="4" y="44" width="22" height="3" rx="1.5"/></g>' +
  "</g>" +
  '<g class="bob"><g transform="translate(176 30)"><rect x="-23" y="-9" width="46" height="16" rx="8" class="pp" />' +
  '<text x="0" y="2.4" class="tx mono s7 mid b" >action()</text></g></g>' +
  "</svg>";

/**
 * Follow-ups: an answer standing on the base, three next steps waiting under
 * it as buttons, and the one about to be pressed lifting off.
 */
const FOLLOW_UPS =
  '<svg viewBox="0 0 240 135" aria-hidden="true" preserveAspectRatio="xMidYMid meet">' +
  '<polygon class="ishb" points="120,46.5 195.7,90.2 120,133.8 44.3,90.2"/>' +
  '<g><polygon class="ict" points="120,33.1 195.7,76.8 120,120.5 44.3,76.8"/>' +
  '<polygon class="icl" points="44.3,82 120,125.7 120,120.5 44.3,76.8"/>' +
  '<polygon class="icr" points="195.7,82 120,125.7 120,120.5 195.7,76.8"/></g>' +
  '<g><polygon class="int" points="120,30 195.7,73.7 120,117.4 44.3,73.7"/>' +
  '<polygon class="inl" points="44.3,76.8 120,120.5 120,117.4 44.3,73.7"/>' +
  '<polygon class="inr" points="195.7,76.8 120,120.5 120,117.4 195.7,73.7"/></g>' +
  '<g transform="matrix(0.9 0.5 -0.9 0.5 120 30)"><path class="igrid2" d="M21 3V81M42 3V81M63 3V81M3 21H81M3 42H81M3 63H81"/></g>' +
  '<polygon class="int" points="71.2,22 128.8,54 126.6,55 69.4,23"/>' +
  '<polygon class="inr" points="128.8,54 128.8,84 126.6,85 126.6,55"/>' +
  '<polygon class="inl" points="69.4,53 126.6,85 126.6,55 69.4,23"/>' +
  '<g transform="matrix(0.9 0.5 0 1 69.4 23)">' +
  '<rect x="6" y="8" width="44" height="3" rx="1.5" class="mu" />' +
  '<rect x="6" y="14" width="36" height="3" rx="1.5" class="mu" />' +
  '<rect x="6" y="20" width="40" height="3" rx="1.5" class="mu" /></g>' +
  '<g class="breathe" style="animation-delay:0s"><g transform="matrix(0.9 0.5 0 1 136 64)">' +
  '<rect x="0" y="0" width="30" height="8" rx="4" class="ict" /></g></g>' +
  '<g class="breathe" style="animation-delay:-0.6s"><g transform="matrix(0.9 0.5 0 1 150 72)">' +
  '<rect x="0" y="0" width="30" height="8" rx="4" class="ict" /></g></g>' +
  '<g class="bob"><g transform="matrix(0.9 0.5 0 1 164 64)">' +
  '<rect x="0" y="0" width="30" height="8" rx="4" class="ac" /></g></g>' +
  '<g class="bob"><g transform="translate(176 36)"><rect x="-19" y="-9" width="38" height="16" rx="8" class="pp" />' +
  '<text x="0" y="2.4" class="tx mono s7 mid b" >next →</text></g></g>' +
  "</svg>";

/** Tables: a slab on the base ruled into rows, a few cells filled in, and `rows` above. */
const VIRTUAL_TABLES =
  '<svg viewBox="0 0 240 135" aria-hidden="true" preserveAspectRatio="xMidYMid meet">' +
  '<polygon class="ishb" points="120,46.5 195.7,90.2 120,133.8 44.3,90.2"/>' +
  '<g><polygon class="ict" points="120,33.1 195.7,76.8 120,120.5 44.3,76.8"/>' +
  '<polygon class="icl" points="44.3,82 120,125.7 120,120.5 44.3,76.8"/>' +
  '<polygon class="icr" points="195.7,82 120,125.7 120,120.5 195.7,76.8"/></g>' +
  '<g><polygon class="int" points="120,30 195.7,73.7 120,117.4 44.3,73.7"/>' +
  '<polygon class="inl" points="44.3,76.8 120,120.5 120,117.4 44.3,73.7"/>' +
  '<polygon class="inr" points="195.7,76.8 120,120.5 120,117.4 195.7,73.7"/></g>' +
  '<g transform="matrix(0.9 0.5 -0.9 0.5 120 30)"><path class="igrid2" d="M21 3V81M42 3V81M63 3V81M3 21H81M3 42H81M3 63H81"/></g>' +
  '<g transform="matrix(0.9 0.5 -0.9 0.5 120 30)">' +
  '<rect x="9" y="9" width="63" height="9" rx="2" class="ac" />' +
  '<g class="breathe" style="animation-delay:0s"><rect x="9" y="24" width="63" height="9" rx="2" class="mu" /></g>' +
  '<g class="breathe" style="animation-delay:-0.6s"><rect x="9" y="39" width="63" height="9" rx="2" class="mu" /></g>' +
  '<g class="breathe" style="animation-delay:-1.2s"><rect x="9" y="54" width="63" height="9" rx="2" class="mu" /></g>' +
  '<path class="igrid" d="M30 9V63M51 9V63"/></g>' +
  '<g class="bob"><g transform="translate(172 30)"><rect x="-19" y="-9" width="38" height="16" rx="8" class="pp" />' +
  '<text x="0" y="2.4" class="tx mono s7 mid b" >rows</text></g></g>' +
  "</svg>";

/** Workflows: three steps standing on the base, joined by lines that draw themselves. */
const WORKFLOWS =
  '<svg viewBox="0 0 240 135" aria-hidden="true" preserveAspectRatio="xMidYMid meet">' +
  '<polygon class="ishb" points="120,46.5 195.7,90.2 120,133.8 44.3,90.2"/>' +
  '<g><polygon class="ict" points="120,33.1 195.7,76.8 120,120.5 44.3,76.8"/>' +
  '<polygon class="icl" points="44.3,82 120,125.7 120,120.5 44.3,76.8"/>' +
  '<polygon class="icr" points="195.7,82 120,125.7 120,120.5 195.7,76.8"/></g>' +
  '<g><polygon class="int" points="120,30 195.7,73.7 120,117.4 44.3,73.7"/>' +
  '<polygon class="inl" points="44.3,76.8 120,120.5 120,117.4 44.3,73.7"/>' +
  '<polygon class="inr" points="195.7,76.8 120,120.5 120,117.4 195.7,73.7"/></g>' +
  '<g transform="matrix(0.9 0.5 -0.9 0.5 120 30)"><path class="igrid2" d="M21 3V81M42 3V81M63 3V81M3 21H81M3 42H81M3 63H81"/></g>' +
  '<g transform="matrix(0.9 0.5 -0.9 0.5 120 30)">' +
  '<path class="ln w2 draw" pathLength="100" d="M21 21H60V60"/></g>' +
  '<g><polygon class="ict" points="108,34 120.6,41.3 108,48.6 95.4,41.3"/>' +
  '<polygon class="icl" points="95.4,52 108,59.3 108,48.6 95.4,41.3"/>' +
  '<polygon class="icr" points="120.6,52 108,59.3 108,48.6 120.6,41.3"/></g>' +
  '<g><polygon class="ict" points="146.4,56 159,63.3 146.4,70.6 133.8,63.3"/>' +
  '<polygon class="icl" points="133.8,74 146.4,81.3 146.4,70.6 133.8,63.3"/>' +
  '<polygon class="icr" points="159,74 146.4,81.3 146.4,70.6 159,63.3"/></g>' +
  '<g><polygon class="ict" points="108,78 120.6,85.3 108,92.6 95.4,85.3"/>' +
  '<polygon class="icl" points="95.4,96 108,103.3 108,92.6 95.4,85.3"/>' +
  '<polygon class="icr" points="120.6,96 108,103.3 108,92.6 120.6,85.3"/></g>' +
  '<g class="bob"><g transform="translate(172 30)"><rect x="-19" y="-9" width="38" height="16" rx="8" class="pp" />' +
  '<text x="0" y="2.4" class="tx mono s7 mid b" >run()</text></g></g>' +
  "</svg>";

export const DRAWN_ART: Readonly<Record<string, string>> = {
  visuals: VISUALS,
  background_tools: BACKGROUND_TOOLS,
  virtual_tables: VIRTUAL_TABLES,
  workflows: WORKFLOWS,
  monitor: MONITOR,
  text_to_speech: TEXT_TO_SPEECH,
  computer_use: COMPUTER_USE,
  video_generation: VIDEO_GENERATION,
  follow_ups: FOLLOW_UPS,
};
