/*
 * AgenticOS world map kit, version 1 - served to published artifacts, as `window.AOWorldMap`.
 *
 * A map of the world drawn as plain SVG from country outlines the deployment
 * serves itself: no tile server, no network and no extra container, so it draws
 * the same on an air-gapped deployment. It shades countries by a value, marks
 * places with pins and joins two places with a great-circle line.
 *
 *   AOWorldMap.draw(element, {
 *     countries: { Poland: 12, Germany: 7 }      // or [{ name, value, note }]; shades by value
 *     highlight: ["Poland"],                     // emphasises countries that have no value
 *     pins:   [{ name, lat, lng, size, note }],
 *     routes: [{ from: { lat, lng } | "Warsaw" pin name, to: ..., label }],
 *     focus:  ["Poland", "Germany"],             // zoom to these countries
 *     projection: "natural-earth" | "mercator" | "equal-earth",
 *     legend: "Customers",                       // names what the shading counts
 *     format: function (value) { return String(value); }
 *   })
 *
 * It needs, in this order: `lib/d3-7.9.0.min.js`, `lib/topojson-client-3.1.0.min.js`,
 * `lib/world-atlas-2.0.2-110m.js`, then this file. A country is named as the data
 * names it ("United States of America", "Czechia"), by a common alias ("USA",
 * "UK"), or by its ISO 3166-1 numeric code ("616"); `draw` returns
 * `{ unmatched }` listing every name it could not place, so a page can say so.
 *
 * Country outlines: Natural Earth (public domain) through world-atlas 2.0.2 (ISC).
 * This file is Apache-2.0 like the rest of the repository; a change that alters an
 * existing page is agenticos-worldmap-2.js, never an edit of this one.
 */
(function () {
  "use strict";

  var STYLE = [
    ".aow{--aow-fg:var(--ao-fg,#18181b);--aow-muted:var(--ao-muted-fg,#71717a);--aow-line:var(--ao-border-strong,#d4d4d8);",
    "--aow-fill:var(--ao-muted,#f4f4f5);--aow-card:var(--ao-card,#fff);--aow-ink:var(--ao-primary,#18181b);--aow-on-ink:var(--ao-primary-fg,#fafafa);",
    "position:relative;font:14px/1.5 var(--ao-font,system-ui,sans-serif);color:var(--aow-fg)}",
    "@media (prefers-color-scheme:dark){.aow{--aow-fg:var(--ao-fg,#fafafa);--aow-muted:var(--ao-muted-fg,#a1a1aa);--aow-line:var(--ao-border-strong,#52525b);",
    "--aow-fill:var(--ao-muted,#27272a);--aow-card:var(--ao-card,#1f1f23);--aow-ink:var(--ao-primary,#fafafa);--aow-on-ink:var(--ao-primary-fg,#18181b)}}",
    ".aow svg{display:block;width:100%;height:auto}",
    ".aow-country{fill:var(--aow-fill);stroke:var(--aow-card);stroke-width:.6;outline:none}",
    ".aow-country[data-level]{fill:var(--aow-ink)}",
    ".aow-country[data-level='1']{fill-opacity:.2}.aow-country[data-level='2']{fill-opacity:.38}",
    ".aow-country[data-level='3']{fill-opacity:.56}.aow-country[data-level='4']{fill-opacity:.74}",
    ".aow-country[data-level='5']{fill-opacity:.92}",
    ".aow-country[data-hl]{fill:var(--aow-ink);fill-opacity:.85}",
    ".aow-country:focus-visible,.aow-pin:focus-visible{stroke:var(--aow-fg);stroke-width:2}",
    ".aow-route{fill:none;stroke:var(--aow-ink);stroke-width:1.8;stroke-dasharray:5 5;stroke-linecap:round;opacity:.8}",
    ".aow-pin{fill:var(--aow-card);stroke:var(--aow-ink);stroke-width:2;outline:none;cursor:default}",
    ".aow-tip{position:absolute;pointer-events:none;transform:translate(-50%,-110%);white-space:nowrap;font-size:12px;",
    "padding:3px 8px;border-radius:6px;background:var(--aow-card);color:var(--aow-fg);box-shadow:0 1px 4px rgba(0,0,0,.3);display:none}",
    ".aow-legend{display:flex;align-items:center;gap:8px;margin:8px 2px 0;font-size:12px;color:var(--aow-muted)}",
    ".aow-swatches{display:flex}.aow-swatches i{width:22px;height:8px;background:var(--aow-ink)}",
    ".aow-swatches i:first-child{border-radius:4px 0 0 4px}.aow-swatches i:last-child{border-radius:0 4px 4px 0}",
  ].join("");

  var ALIASES = {
    "usa": "United States of America", "us": "United States of America", "u.s.": "United States of America",
    "united states": "United States of America", "america": "United States of America",
    "uk": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom",
    "czech republic": "Czechia", "ivory coast": "Côte d'Ivoire", "cote d'ivoire": "Côte d'Ivoire",
    "drc": "Dem. Rep. Congo", "democratic republic of the congo": "Dem. Rep. Congo",
    "republic of the congo": "Congo", "bosnia": "Bosnia and Herz.", "bosnia and herzegovina": "Bosnia and Herz.",
    "dominican republic": "Dominican Rep.", "central african republic": "Central African Rep.",
    "equatorial guinea": "Eq. Guinea", "south sudan": "S. Sudan", "falkland islands": "Falkland Is.",
    "solomon islands": "Solomon Is.", "north macedonia": "Macedonia", "swaziland": "eSwatini",
    "burma": "Myanmar", "east timor": "Timor-Leste", "uae": "United Arab Emirates", "turkiye": "Turkey",
    "russian federation": "Russia", "republic of korea": "South Korea", "korea, south": "South Korea",
    "viet nam": "Vietnam", "lao pdr": "Laos", "syrian arab republic": "Syria",
    "palestinian territories": "Palestine", "western sahara": "W. Sahara", "holland": "Netherlands"
  };

  var PROJECTIONS = { "natural-earth": "geoNaturalEarth1", mercator: "geoMercator", "equal-earth": "geoEqualEarth" };
  var PAD = 8;

  function key(name) {
    return String(name).trim().toLowerCase();
  }

  function style() {
    if (document.getElementById("aow-style")) return;
    var tag = document.createElement("style");
    tag.id = "aow-style";
    tag.textContent = STYLE;
    document.head.appendChild(tag);
  }

  function need() {
    if (!window.d3 || !window.topojson || !window.AO_WORLD_110M) {
      throw new Error("AOWorldMap needs d3, topojson-client and world-atlas-2.0.2-110m.js loaded first");
    }
  }

  /** The country features, and how a name or code finds one. */
  function world() {
    var topology = window.AO_WORLD_110M;
    var features = window.topojson.feature(topology, topology.objects.countries).features.filter(function (feature) {
      return feature.properties.name !== "Antarctica";
    });
    var index = {};
    features.forEach(function (feature) {
      index[key(feature.properties.name)] = feature;
      index[String(feature.id)] = feature;
    });
    return {
      features: features,
      find: function (name) {
        var text = key(name);
        return index[text] || index[key(ALIASES[text] || "")] || null;
      }
    };
  }

  /** `{ Poland: 3 }` or `[{ name, value, note }]`, as one list of entries. */
  function entries(countries) {
    if (!countries) return [];
    if (Array.isArray(countries)) return countries;
    return Object.keys(countries).map(function (name) {
      return { name: name, value: countries[name] };
    });
  }

  function svgNode(name, attributes) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.keys(attributes || {}).forEach(function (attribute) {
      node.setAttribute(attribute, attributes[attribute]);
    });
    return node;
  }

  function draw(element, options) {
    need();
    style();
    options = options || {};
    var d3 = window.d3;
    var data = world();
    var unmatched = [];
    var format = options.format || function (value) { return String(value); };

    var shaded = {};
    var highlighted = {};
    var values = [];
    entries(options.countries).forEach(function (entry) {
      var feature = data.find(entry.name);
      if (!feature) return unmatched.push(entry.name);
      shaded[feature.id] = entry;
      if (typeof entry.value === "number") values.push(entry.value);
    });
    (options.highlight || []).forEach(function (name) {
      var feature = data.find(name);
      if (feature) highlighted[feature.id] = true;
      else unmatched.push(name);
    });
    var top = values.length ? Math.max.apply(null, values) : 0;
    var low = values.length ? Math.min.apply(null, values) : 0;
    var level = function (value) {
      if (typeof value !== "number" || top === low) return 5;
      return 1 + Math.min(4, Math.floor(((value - low) / (top - low)) * 5));
    };

    var focus = [];
    (options.focus || []).forEach(function (name) {
      var feature = data.find(name);
      if (feature) focus.push(feature);
      else unmatched.push(name);
    });
    var fitted = { type: "FeatureCollection", features: focus.length ? focus : data.features };

    var width = Math.max(element.clientWidth || 720, 320);
    var projection = d3[PROJECTIONS[options.projection] || PROJECTIONS["natural-earth"]]();
    projection.fitWidth(width - 2 * PAD, fitted);
    var path = d3.geoPath(projection);
    var bounds = path.bounds(fitted);
    var shift = projection.translate();
    projection.translate([shift[0] + PAD - 0, shift[1] + PAD - bounds[0][1]]);
    var height = Math.ceil(bounds[1][1] - bounds[0][1]) + 2 * PAD;

    element.innerHTML = "";
    element.classList.add("aow");
    var svg = svgNode("svg", { viewBox: "0 0 " + width + " " + height, role: "img" });
    svg.setAttribute("aria-label", options.label || "World map");
    var tip = document.createElement("div");
    tip.className = "aow-tip";
    var show = function (target, text) {
      var box = element.getBoundingClientRect();
      var at = target.getBoundingClientRect();
      tip.textContent = text;
      tip.style.left = at.left - box.left + at.width / 2 + "px";
      tip.style.top = at.top - box.top + "px";
      tip.style.display = "block";
    };
    var hide = function () { tip.style.display = "none"; };

    data.features.forEach(function (feature) {
      var entry = shaded[feature.id];
      var node = svgNode("path", { class: "aow-country", d: path(feature) || "" });
      if (entry) node.setAttribute("data-level", String(level(entry.value)));
      else if (highlighted[feature.id]) node.setAttribute("data-hl", "");
      if (entry || highlighted[feature.id]) {
        var text = feature.properties.name + (entry && entry.value !== undefined ? ": " + format(entry.value) : "") +
          (entry && entry.note ? " - " + entry.note : "");
        node.setAttribute("tabindex", "0");
        node.setAttribute("aria-label", text);
        node.addEventListener("pointerenter", function () { show(node, text); });
        node.addEventListener("focus", function () { show(node, text); });
        node.addEventListener("pointerleave", hide);
        node.addEventListener("blur", hide);
      }
      svg.appendChild(node);
    });

    var places = {};
    (options.pins || []).forEach(function (pin) {
      places[key(pin.name)] = pin;
    });
    var place = function (ref) {
      return typeof ref === "string" ? places[key(ref)] : ref;
    };
    (options.routes || []).forEach(function (route) {
      var from = place(route.from);
      var to = place(route.to);
      if (!from || !to) return unmatched.push(typeof route.from === "string" ? route.from : route.to);
      var line = { type: "LineString", coordinates: [[from.lng, from.lat], [to.lng, to.lat]] };
      var node = svgNode("path", { class: "aow-route", d: path(line) || "" });
      if (route.label) node.appendChild(svgNode("title")).textContent = route.label;
      svg.appendChild(node);
    });
    (options.pins || []).forEach(function (pin) {
      var at = projection([pin.lng, pin.lat]);
      if (!at) return;
      var node = svgNode("circle", { class: "aow-pin", cx: at[0], cy: at[1], r: pin.size || 5, tabindex: "0" });
      var text = pin.name + (pin.note ? " - " + pin.note : "");
      node.setAttribute("aria-label", text);
      node.addEventListener("pointerenter", function () { show(node, text); });
      node.addEventListener("focus", function () { show(node, text); });
      node.addEventListener("pointerleave", hide);
      node.addEventListener("blur", hide);
      svg.appendChild(node);
    });

    element.appendChild(svg);
    element.appendChild(tip);
    if (values.length) {
      var legend = document.createElement("div");
      legend.className = "aow-legend";
      legend.innerHTML = "<span></span><span class='aow-swatches'>" +
        [1, 2, 3, 4, 5].map(function (step) { return "<i style='opacity:" + [0.2, 0.38, 0.56, 0.74, 0.92][step - 1] + "'></i>"; }).join("") +
        "</span><span></span>";
      legend.children[0].textContent = format(low);
      legend.children[2].textContent = format(top) + (options.legend ? " " + options.legend : "");
      element.appendChild(legend);
    }
    return { unmatched: unmatched };
  }

  window.AOWorldMap = { draw: draw };
})();
