/*
 * AgenticOS map kit, version 2 - served to published artifacts, as `window.AOMap`.
 *
 * One call draws an itinerary: numbered pins and a line joining them in order,
 * replayed pin by pin on request, and a strip of cards for the stops, each of
 * which can offer a follow-up to the conversation. On the deployment's tile
 * server (`agenticos.map`) it is a real map, through Leaflet
 * (`lib/leaflet-1.9.4/`); without one, or when the tiles do not load, it is a
 * plain outline of the same pins - still correct, never a blank box.
 *
 *   AOMap.itinerary(element, { stops: [{ name, lat, lng, day, note, image,
 *     credit, creditUrl }], followUp: { label, text: function (stop) {...} } })
 *
 * What it offers: AOMap.itinerary, AOMap.animator, AOMap.tiles.
 *
 * The pin-drop timing in `animator` is adapted from `createTripAnimator` in
 * Open Intelligent UI (https://github.com/CopilotKit/OpenIntelligentUI):
 *
 *   The MIT License
 *   Copyright (c) Atai Barkai
 *
 *   Permission is hereby granted, free of charge, to any person obtaining a copy
 *   of this software and associated documentation files (the "Software"), to
 *   deal in the Software without restriction, including without limitation the
 *   rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
 *   sell copies of the Software, and to permit persons to whom the Software is
 *   furnished to do so, subject to the following conditions:
 *
 *   The above copyright notice and this permission notice shall be included in
 *   all copies or substantial portions of the Software.
 *
 *   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 *   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 *   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 *   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 *   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 *   FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
 *   IN THE SOFTWARE.
 *
 * What changed from version 1, which stays served for the pages that name it:
 * the route is shown whole on load and played only on request (`autoplay`), the
 * map grows with the page's width instead of keeping one height, and a frame the
 * page drew around it no longer leaves everything touching its edge.
 *
 * This file is Apache-2.0 like the rest of the repository; never edited in a way
 * that changes an existing page - a change like that is agenticos-map-3.js.
 */
(function () {
  "use strict";

  var STYLE = [
    ".aom{--aom-fg:var(--ao-fg,#18181b);--aom-muted:var(--ao-muted-fg,#71717a);--aom-line:var(--ao-border-strong,#d4d4d8);",
    "--aom-fill:var(--ao-muted,#f4f4f5);--aom-card:var(--ao-card,#fff);--aom-ink:var(--ao-primary,#18181b);--aom-on-ink:var(--ao-primary-fg,#fafafa);",
    "font:14px/1.5 var(--ao-font,system-ui,sans-serif);color:var(--aom-fg)}",
    "@media (prefers-color-scheme:dark){.aom{--aom-fg:var(--ao-fg,#fafafa);--aom-muted:var(--ao-muted-fg,#a1a1aa);--aom-line:var(--ao-border-strong,#52525b);",
    "--aom-fill:var(--ao-muted,#27272a);--aom-card:var(--ao-card,#1f1f23);--aom-ink:var(--ao-primary,#fafafa);--aom-on-ink:var(--ao-primary-fg,#18181b)}}",
    ".aom-map{position:relative;border-radius:12px;overflow:hidden;background:var(--aom-fill)}",
    ".aom-map .leaflet-container{width:100%;height:100%;background:var(--aom-fill);font:inherit}",
    ".aom-outline{position:absolute;inset:0;width:100%;height:100%}",
    ".aom-outline .aom-grid{stroke:var(--aom-line);stroke-width:1;opacity:.5}",
    ".aom-route{fill:none;stroke:var(--aom-ink);stroke-width:2.5;stroke-dasharray:6 6;stroke-linecap:round;opacity:.75}",
    ".aom-place{position:absolute;transform:translate(-50%,-50%)}",
    ".aom-pin{display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;",
    "background:var(--aom-card);color:var(--aom-fg);border:2px solid var(--aom-ink);font-weight:600;font-size:12px;",
    "box-shadow:0 1px 3px rgba(0,0,0,.25);cursor:pointer;opacity:0}",
    ".aom-pin.aom-active{background:var(--aom-ink);color:var(--aom-on-ink)}",
    ".aom-label{position:absolute;left:50%;top:30px;transform:translateX(-50%);white-space:nowrap;font-size:12px;font-weight:500;",
    "padding:1px 6px;border-radius:6px;background:var(--aom-card);opacity:.92}",
    ".aom-divicon{background:none;border:0}",
    ".aom-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0 0}",
    ".aom-button{font:inherit;font-size:13px;font-weight:500;color:var(--aom-fg);background:var(--aom-fill);border:0;",
    "border-radius:999px;padding:5px 12px;cursor:pointer}",
    ".aom-button:disabled{opacity:.5;cursor:default}",
    ".aom-button:focus-visible,.aom-pin:focus-visible,.aom-card:focus-visible{outline:2px solid var(--aom-ink);outline-offset:2px}",
    ".aom-status{font-size:13px;color:var(--aom-muted);flex:1;min-width:8rem}",
    ".aom-note{font-size:12px;color:var(--aom-muted);margin:6px 0 0}",
    ".aom-note a{color:inherit}",
    ".aom-cards{display:flex;gap:10px;overflow-x:auto;padding:10px 0 4px;margin:0;list-style:none;scroll-behavior:smooth}",
    ".aom-card{flex:0 0 200px;background:var(--aom-fill);border-radius:12px;overflow:hidden;cursor:pointer;",
    "border:2px solid transparent;display:flex;flex-direction:column}",
    ".aom-card.aom-active{border-color:var(--aom-ink)}",
    ".aom-card img{display:block;width:100%;height:110px;object-fit:cover}",
    ".aom-card-body{padding:8px 10px 10px;display:flex;flex-direction:column;gap:2px;flex:1}",
    ".aom-card-day{font-size:12px;color:var(--aom-muted)}",
    ".aom-card-name{font-weight:600}",
    ".aom-card-text{font-size:13px;color:var(--aom-muted)}",
    ".aom-credit{font-size:11px;color:var(--aom-muted)}",
    ".aom-card .aom-button{margin-top:6px;align-self:flex-start;background:var(--aom-card)}",
    "@media (prefers-reduced-motion:reduce){.aom-cards{scroll-behavior:auto}}",
  ].join("");

  var DEFAULT_LABELS = {
    pause: "Pause",
    resume: "Resume",
    replay: "Replay",
    stop: "Stop {n} of {total}: {name}",
    done: "All {total} stops shown",
    illustrative: "Lines join the stops in order - they are not directions.",
    outline: "No map tiles here, so this is an outline of the stops.",
    tilesFailed: "The map tiles did not load, so this is an outline of the stops.",
  };

  function tiles() {
    var host = window.agenticos;
    return host && host.map ? host.map : null;
  }

  function addStyle() {
    if (document.getElementById("aom-style")) return;
    var style = document.createElement("style");
    style.id = "aom-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function fill(template, values) {
    return String(template).replace(/\{(\w+)\}/g, function (match, key) {
      return values[key] === undefined ? match : String(values[key]);
    });
  }

  function reducedMotion() {
    return window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)").matches : false;
  }

  /**
   * Pins dropped one after another over `durationMs`, as frames.
   *
   * `onFrame({ progress, pinIndex, pinProgress, activeStop })` runs at once and
   * on every frame; the returned controller plays, pauses, replays and seeks. It
   * pauses when the page is hidden and shows every pin at once for a reader who
   * asked for less motion.
   */
  function animator(options) {
    var count = options.stopCount;
    var duration = options.durationMs || 6000;
    if (!(count >= 1 && count <= 60)) throw new Error("An itinerary has 1-60 stops.");
    var elapsed = 0;
    var last = null;
    var frame = null;
    var playing = false;
    var disposed = false;
    function emit() {
      var progress = Math.min(1, elapsed / duration);
      var step = progress * count;
      var pinIndex = Math.min(count - 1, Math.floor(step));
      var pinProgress = progress === 1 ? 1 : Math.min(1, (step - pinIndex) / 0.55);
      (options.pins || []).forEach(function (pin, index) {
        var landing = index < pinIndex ? 1 : index === pinIndex ? pinProgress : 0;
        var t = landing - 1;
        var ease = 1 + 2.2 * t * t * t + 1.2 * t * t;
        pin.style.opacity = landing > 0 ? "1" : "0";
        pin.style.transform = "translateY(" + -18 * (1 - ease) + "px) scale(" + (0.72 + 0.28 * ease) + ")";
      });
      options.onFrame({ progress: progress, pinIndex: pinIndex, pinProgress: pinProgress, activeStop: pinIndex });
    }
    function state(name) { if (options.onState) options.onState(name); }
    function pause() {
      if (disposed) return;
      playing = false;
      last = null;
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      state(elapsed >= duration ? "complete" : "paused");
    }
    function tick(time) {
      if (!playing || disposed) return;
      if (last !== null) elapsed = Math.min(duration, elapsed + Math.max(0, time - last));
      last = time;
      emit();
      if (elapsed >= duration) pause();
      else frame = requestAnimationFrame(tick);
    }
    function play() {
      if (disposed || playing) return;
      if (reducedMotion()) {
        elapsed = duration;
        emit();
        state("complete");
        return;
      }
      if (elapsed >= duration) return;
      playing = true;
      last = null;
      state("playing");
      frame = requestAnimationFrame(tick);
    }
    function seek(stop) {
      if (disposed || stop < 0 || stop >= count) return;
      pause();
      elapsed = stop === count - 1 ? duration : (duration * (stop + 0.6)) / count;
      emit();
      state(elapsed >= duration ? "complete" : "paused");
    }
    function replay() {
      if (disposed) return;
      pause();
      elapsed = 0;
      emit();
      play();
    }
    function hidden() { if (document.hidden) pause(); }
    function dispose() {
      if (disposed) return;
      pause();
      disposed = true;
      document.removeEventListener("visibilitychange", hidden);
    }
    document.addEventListener("visibilitychange", hidden);
    if (reducedMotion()) elapsed = duration;
    emit();
    return { play: play, pause: pause, replay: replay, seek: seek, dispose: dispose, playing: function () { return playing; } };
  }

  function validStops(stops) {
    if (!Array.isArray(stops) || stops.length === 0) throw new Error("AOMap.itinerary needs `stops`.");
    return stops.map(function (stop, index) {
      var lat = Number(stop.lat);
      var lng = Number(stop.lng);
      if (!isFinite(lat) || !isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
        throw new Error("Stop " + (index + 1) + " needs a `lat` and `lng` in degrees.");
      }
      return { stop: stop, lat: lat, lng: lng, number: index + 1 };
    });
  }

  function makePin(number, name) {
    var pin = element("button", "aom-pin", number);
    pin.type = "button";
    pin.setAttribute("aria-label", number + ". " + name);
    return pin;
  }

  /** The stops drawn on a plain projection when there is no map underneath. */
  function drawOutline(box, places, labels) {
    var width = box.clientWidth || 640;
    var height = box.clientHeight || 320;
    var meanLat = places.reduce(function (sum, p) { return sum + p.lat; }, 0) / places.length;
    var scaleX = Math.cos((meanLat * Math.PI) / 180) || 1;
    var xs = places.map(function (p) { return p.lng * scaleX; });
    var ys = places.map(function (p) { return -p.lat; });
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    var pad = 48;
    var span = Math.max(maxX - minX, maxY - minY, 0.01);
    var scale = Math.min((width - pad * 2) / Math.max(maxX - minX, span / 4), (height - pad * 2) / Math.max(maxY - minY, span / 4));
    var offsetX = (width - (maxX - minX) * scale) / 2;
    var offsetY = (height - (maxY - minY) * scale) / 2;
    var points = places.map(function (p, i) {
      return [offsetX + (xs[i] - minX) * scale, offsetY + (ys[i] - minY) * scale];
    });
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "aom-outline");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    // Stretched with the box, and the pins placed in percentages of it, so the
    // two stay together when the column narrows or a phone turns.
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    for (var gx = 0; gx <= width; gx += 48) {
      var v = document.createElementNS(ns, "line");
      v.setAttribute("class", "aom-grid");
      v.setAttribute("vector-effect", "non-scaling-stroke");
      v.setAttribute("x1", gx); v.setAttribute("x2", gx); v.setAttribute("y1", 0); v.setAttribute("y2", height);
      svg.appendChild(v);
    }
    for (var gy = 0; gy <= height; gy += 48) {
      var h = document.createElementNS(ns, "line");
      h.setAttribute("class", "aom-grid");
      h.setAttribute("vector-effect", "non-scaling-stroke");
      h.setAttribute("x1", 0); h.setAttribute("x2", width); h.setAttribute("y1", gy); h.setAttribute("y2", gy);
      svg.appendChild(h);
    }
    var route = document.createElementNS(ns, "polyline");
    route.setAttribute("class", "aom-route");
    route.setAttribute("vector-effect", "non-scaling-stroke");
    svg.appendChild(route);
    box.appendChild(svg);
    var pins = places.map(function (p, i) {
      var place = element("div", "aom-place");
      place.style.left = (points[i][0] / width) * 100 + "%";
      place.style.top = (points[i][1] / height) * 100 + "%";
      var pin = makePin(p.number, p.stop.name);
      place.appendChild(pin);
      place.appendChild(element("span", "aom-label", p.stop.name));
      box.appendChild(place);
      return pin;
    });
    return {
      pins: pins,
      showRoute: function (shown) {
        route.setAttribute("points", points.slice(0, shown).map(function (pt) { return pt.join(","); }).join(" "));
      },
      focus: function () {},
      note: labels.outline,
    };
  }

  /** The stops on the deployment's tile server, through Leaflet. */
  function drawLeaflet(box, places, server, onTilesFailed) {
    var L = window.L;
    // The credit goes in the note under the map, with the line about the route,
    // rather than in a corner the pins can cover.
    var map = L.map(box, { scrollWheelZoom: false, zoomControl: true, attributionControl: false });
    // `server.url` is this deployment's own tile path, which fetches the tiles
    // from the tile server: a page never talks to it.
    var layer = L.tileLayer(server.url, { maxZoom: server.maxZoom });
    var loaded = 0;
    var failed = 0;
    layer.on("tileload", function () { loaded += 1; });
    layer.on("tileerror", function () {
      failed += 1;
      if (loaded === 0 && failed >= 4) onTilesFailed();
    });
    layer.addTo(map);
    var latlngs = places.map(function (p) { return [p.lat, p.lng]; });
    var route = L.polyline([], { className: "aom-route", interactive: false }).addTo(map);
    var pins = places.map(function (p) {
      var pin = makePin(p.number, p.stop.name);
      var icon = L.divIcon({ className: "aom-divicon", html: pin, iconSize: [26, 26], iconAnchor: [13, 13] });
      L.marker([p.lat, p.lng], { icon: icon, keyboard: false, title: p.stop.name }).addTo(map);
      return pin;
    });
    if (latlngs.length === 1) map.setView(latlngs[0], Math.min(12, server.maxZoom));
    else map.fitBounds(L.latLngBounds(latlngs), { padding: [36, 36], maxZoom: Math.min(13, server.maxZoom) });
    setTimeout(function () { map.invalidateSize(); }, 0);
    if (window.ResizeObserver) {
      new ResizeObserver(function () { map.invalidateSize(); }).observe(box);
    }
    return {
      pins: pins,
      showRoute: function (shown) { route.setLatLngs(latlngs.slice(0, shown)); },
      focus: function (index) {
        if (!map.getBounds().contains(latlngs[index])) map.panTo(latlngs[index], { animate: !reducedMotion() });
      },
      remove: function () { map.remove(); },
      attribution: server,
    };
  }

  function offerFollowUp(button) {
    function show() {
      var host = window.agenticos;
      button.hidden = !(host && host.canFollowUp && host.canFollowUp());
    }
    show();
    window.addEventListener("agenticos:host", show);
  }

  /**
   * Draw an itinerary into `target`.
   *
   * options.stops        [{ name, lat, lng, day, note, image, imageAlt, credit, creditUrl }]
   * options.height       the map's least height in pixels (320); it is 16:9 of the
   *                      page's width when that is taller
   * options.route        join the stops with a line (true)
   * options.autoplay     drop the pins one by one on load (false: shown at once)
   * options.durationMs   how long dropping them all takes (6000)
   * options.followUp     { label, text: function (stop, number) } - a button on each card
   *                      that asks to continue the conversation about that stop
   * options.labels       the words, in the reader's language - see DEFAULT_LABELS
   */
  function itinerary(target, options) {
    addStyle();
    var root = typeof target === "string" ? document.querySelector(target) : target;
    if (!root) throw new Error("AOMap.itinerary: no element to draw into.");
    var opts = options || {};
    var labels = {};
    Object.keys(DEFAULT_LABELS).forEach(function (key) {
      labels[key] = (opts.labels && opts.labels[key]) || DEFAULT_LABELS[key];
    });
    var places = validStops(opts.stops);
    var showRoute = opts.route !== false;
    root.classList.add("aom");
    // A frame the page drew around the map - a border and no padding - would
    // leave the map, the buttons and the cards touching its edge. Inline, so a
    // page rule naming the element by id cannot take the room back.
    var host = window.getComputedStyle(root);
    if (parseFloat(host.borderTopWidth) > 0 && parseFloat(host.paddingLeft) === 0) {
      root.style.padding = "12px";
      root.style.boxSizing = "border-box";
    }
    root.textContent = "";

    var box = element("div", "aom-map");
    // As wide as the page and 16:9 of it, never lower than `height`: one fixed
    // height read as a strip in a wide window and in full screen.
    box.style.minHeight = (opts.height || 320) + "px";
    box.style.aspectRatio = "16 / 9";
    root.appendChild(box);
    var bar = element("div", "aom-bar");
    var toggle = element("button", "aom-button", labels.pause);
    toggle.type = "button";
    var again = element("button", "aom-button", labels.replay);
    again.type = "button";
    var status = element("span", "aom-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    bar.appendChild(toggle);
    bar.appendChild(again);
    bar.appendChild(status);
    root.appendChild(bar);
    var note = element("p", "aom-note");
    root.appendChild(note);
    var list = element("ol", "aom-cards");
    root.appendChild(list);

    var cards = places.map(function (p) {
      var stop = p.stop;
      var card = element("li", "aom-card");
      card.tabIndex = 0;
      if (stop.image) {
        var img = element("img");
        img.src = stop.image;
        img.alt = stop.imageAlt || stop.name;
        card.appendChild(img);
      }
      var body = element("div", "aom-card-body");
      body.appendChild(element("span", "aom-card-day", stop.day ? p.number + " · " + stop.day : p.number));
      body.appendChild(element("span", "aom-card-name", stop.name));
      if (stop.note) body.appendChild(element("span", "aom-card-text", stop.note));
      if (stop.credit) {
        var credit = element(stop.creditUrl ? "a" : "span", "aom-credit", stop.credit);
        if (stop.creditUrl) credit.href = stop.creditUrl;
        body.appendChild(credit);
      }
      if (opts.followUp && typeof opts.followUp.text === "function") {
        var ask = element("button", "aom-button", opts.followUp.label || "Ask about this");
        ask.type = "button";
        offerFollowUp(ask);
        ask.addEventListener("click", function (event) {
          event.stopPropagation();
          window.agenticos.followUp(opts.followUp.text(stop, p.number));
        });
        body.appendChild(ask);
      }
      card.appendChild(body);
      list.appendChild(card);
      return card;
    });

    var server = tiles();
    var drawing = null;
    var controller = null;
    var active = -1;

    function noteFor(current) {
      note.textContent = "";
      var parts = [];
      if (showRoute && places.length > 1) parts.push(labels.illustrative);
      if (current.note) parts.push(current.note);
      note.appendChild(document.createTextNode(parts.join(" ")));
      if (current.attribution) {
        if (parts.length) note.appendChild(document.createTextNode(" "));
        var source = current.attribution;
        var credit = element(source.attributionUrl ? "a" : "span", "", source.attribution);
        if (source.attributionUrl) credit.href = source.attributionUrl;
        note.appendChild(credit);
      }
    }

    function activate(index) {
      if (index === active) return;
      active = index;
      cards.forEach(function (card, i) {
        card.classList.toggle("aom-active", i === index);
        if (i === index) card.setAttribute("aria-current", "step");
        else card.removeAttribute("aria-current");
      });
      drawing.pins.forEach(function (pin, i) { pin.classList.toggle("aom-active", i === index); });
      var card = cards[index];
      var max = list.scrollWidth - list.clientWidth;
      list.scrollLeft = Math.max(0, Math.min(max, card.offsetLeft - list.offsetLeft - 8));
      status.textContent = fill(labels.stop, { n: index + 1, total: places.length, name: places[index].stop.name });
    }

    function wire() {
      if (controller) controller.dispose();
      active = -1;
      controller = animator({
        stopCount: places.length,
        durationMs: opts.durationMs || 6000,
        pins: drawing.pins,
        onFrame: function (frame) {
          if (showRoute) drawing.showRoute(frame.pinIndex + (frame.pinProgress >= 0.7 ? 1 : 0));
          activate(frame.activeStop);
        },
        onState: function (name) {
          toggle.textContent = name === "playing" ? labels.pause : labels.resume;
          toggle.disabled = name === "complete";
          if (name === "complete") status.textContent = fill(labels.done, { total: places.length });
        },
      });
      drawing.pins.forEach(function (pin, i) {
        pin.addEventListener("click", function () { choose(i); });
      });
      if (opts.autoplay === true) controller.play();
      else showAll();
    }

    // The whole route at once, with no stop picked: what a reader wants first,
    // where pins dropping on every load were something to wait out.
    function showAll() {
      controller.seek(places.length - 1);
      active = -1;
      cards.forEach(function (card) {
        card.classList.remove("aom-active");
        card.removeAttribute("aria-current");
      });
      drawing.pins.forEach(function (pin) { pin.classList.remove("aom-active"); });
      list.scrollLeft = 0;
      status.textContent = fill(labels.done, { total: places.length });
    }

    function choose(index) {
      controller.seek(index);
      drawing.focus(index);
    }

    function outline(reason) {
      if (drawing && drawing.remove) drawing.remove();
      box.textContent = "";
      drawing = drawOutline(box, places, labels);
      drawing.note = reason;
      noteFor(drawing);
      wire();
    }

    if (server && window.L) {
      drawing = drawLeaflet(box, places, server, function () { outline(labels.tilesFailed); });
      noteFor(drawing);
      wire();
    } else {
      outline(labels.outline);
    }

    cards.forEach(function (card, i) {
      card.addEventListener("click", function () { choose(i); });
      card.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose(i);
        }
      });
    });
    toggle.addEventListener("click", function () {
      if (controller.playing()) controller.pause();
      else controller.play();
    });
    again.addEventListener("click", function () { controller.replay(); });

    return {
      play: function () { controller.play(); },
      pause: function () { controller.pause(); },
      replay: function () { controller.replay(); },
      seek: choose,
    };
  }

  window.AOMap = { itinerary: itinerary, animator: animator, tiles: tiles };
})();
