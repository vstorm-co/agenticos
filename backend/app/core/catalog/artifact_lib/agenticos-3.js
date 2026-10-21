/*
 * AgenticOS page kit, version 3 - served to published artifacts, as `window.AO`.
 *
 * The behaviour half of agenticos-3.css. Load it after the libraries it
 * dresses and before the page's own script:
 *
 *   <script src="lib/chart-4.5.1.umd.min.js"></script>
 *   <script src="lib/lucide-1.46.0.min.js"></script>
 *   <script src="lib/agenticos-3.js"></script>
 *
 * What it does on its own: gives Chart.js the console's fonts, grid, tooltip and
 * series colours; turns every <i data-lucide="name"> into its icon - including
 * one a script adds later, as a live page's records arrive after the page has
 * loaded; wires every [data-ao-tabs] group to its panels. What it offers:
 * AO.chart, AO.format, AO.series, AO.color, AO.icons, AO.tabs (all as in
 * version 2), AO.onData (the data bridge's agenticos.onData) and AO.records
 * (a bound view's records drawn as a finished table).
 *
 * Versioned like the stylesheet: a change that would alter an existing page is
 * agenticos-4.js.
 */
(function () {
  "use strict";

  var root = document.documentElement;
  var dark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var charts = [];

  function color(name) {
    return getComputedStyle(root).getPropertyValue(name).trim();
  }

  function series(count) {
    var colors = [];
    for (var i = 0; i < count; i += 1) colors.push(color("--ao-series-" + ((i % 6) + 1)));
    return colors;
  }

  function locale() {
    return root.lang || navigator.language || "en";
  }

  function numberFormat(options) {
    return new Intl.NumberFormat(locale(), options);
  }

  var format = {
    /** 36924 -> "36,924" (or "36 924" under lang="pl"). */
    number: function (value, options) {
      return numberFormat(options).format(value);
    },
    /** 148420 -> "148K". */
    compact: function (value) {
      return numberFormat({ notation: "compact", maximumFractionDigits: 1 }).format(value);
    },
    /** A ratio: 0.411 -> "41.1%". */
    percent: function (ratio, digits) {
      var d = digits === undefined ? 1 : digits;
      return numberFormat({ style: "percent", maximumFractionDigits: d }).format(ratio);
    },
    /** 48200 in EUR -> "€48,200"; pass { minimumFractionDigits: 2, maximumFractionDigits: 2 } for cents. */
    currency: function (value, code, options) {
      var opts = { style: "currency", currency: code || "USD", minimumFractionDigits: 0, maximumFractionDigits: 0 };
      for (var key in options || {}) opts[key] = options[key];
      return numberFormat(opts).format(value);
    },
    /** A date or an ISO string, as the reader's language writes it. */
    date: function (value, options) {
      var date = value instanceof Date ? value : new Date(value);
      return new Intl.DateTimeFormat(locale(), options || { dateStyle: "medium" }).format(date);
    },
    /** A signed change: 37 -> "+37", -0.281 with { percent: true } -> "−28.1%". */
    delta: function (value, options) {
      var opts = options || {};
      var text = opts.percent
        ? format.percent(Math.abs(value), opts.digits)
        : format.number(Math.abs(value), { maximumFractionDigits: opts.digits === undefined ? 1 : opts.digits });
      if (value > 0) return "+" + text;
      if (value < 0) return "−" + text;
      return text;
    },
  };

  function applyChartDefaults() {
    var Chart = window.Chart;
    if (!Chart) return;
    var d = Chart.defaults;
    d.font.family = color("--ao-font");
    d.font.size = 12;
    d.color = color("--ao-muted-fg");
    d.borderColor = color("--ao-border");
    d.maintainAspectRatio = false;
    d.responsive = true;
    d.animation.duration = 400;
    d.interaction.mode = "index";
    d.interaction.intersect = false;
    d.plugins.colors = { enabled: false };
    d.plugins.legend.position = "bottom";
    d.plugins.legend.align = "start";
    d.plugins.legend.labels.usePointStyle = true;
    d.plugins.legend.labels.pointStyle = "rectRounded";
    d.plugins.legend.labels.boxWidth = 8;
    d.plugins.legend.labels.boxHeight = 8;
    d.plugins.legend.labels.padding = 16;
    d.plugins.tooltip.backgroundColor = color("--ao-card");
    d.plugins.tooltip.titleColor = color("--ao-fg");
    d.plugins.tooltip.bodyColor = color("--ao-muted-fg");
    d.plugins.tooltip.borderColor = color("--ao-border");
    d.plugins.tooltip.borderWidth = 1;
    d.plugins.tooltip.padding = 10;
    d.plugins.tooltip.cornerRadius = 8;
    d.plugins.tooltip.boxPadding = 4;
    d.plugins.tooltip.usePointStyle = true;
    d.elements.bar.borderRadius = 4;
    d.elements.line.tension = 0.3;
    d.elements.line.borderWidth = 2;
    d.elements.point.radius = 0;
    d.elements.point.hoverRadius = 4;
    d.elements.arc.borderWidth = 0;
    d.scale.grid.color = color("--ao-border");
    d.scale.border = { display: false };
    d.scale.ticks.padding = 8;
    // Bars and lines are read against the value axis; lines across the categories
    // too are a grid to read through.
    if (d.scales.linear) {
      d.scales.linear.ticks = Object.assign({}, d.scales.linear.ticks, { maxTicksLimit: 6 });
    }
    if (d.scales.category) {
      d.scales.category.grid = Object.assign({}, d.scales.category.grid, { display: false });
    }
  }

  /*
   * Datasets the page did not colour get the series palette, in order. A page
   * that sets its own colours keeps them.
   */
  var seriesPlugin = {
    id: "aoSeries",
    beforeUpdate: function (chart) {
      var type = chart.config.type;
      var datasets = chart.data.datasets || [];
      var palette = series(Math.max(datasets.length, 6));
      datasets.forEach(function (dataset, i) {
        if (type === "doughnut" || type === "pie" || type === "polarArea") {
          if (dataset.backgroundColor === undefined) {
            dataset.backgroundColor = series((chart.data.labels || []).length || 1);
          }
          return;
        }
        if (dataset.borderColor === undefined) dataset.borderColor = palette[i];
        if (dataset.backgroundColor === undefined) dataset.backgroundColor = palette[i];
      });
    },
  };

  if (window.Chart) {
    applyChartDefaults();
    window.Chart.register(seriesPlugin);
  }

  /**
   * A chart that follows light and dark. Pass a function returning the config, so
   * it can be built again with the other theme's colours when the reader switches.
   */
  function chart(target, config) {
    var element = typeof target === "string" ? document.querySelector(target) : target;
    var build = typeof config === "function" ? config : function () { return config; };
    var entry = { element: element, build: build, instance: new window.Chart(element, build()) };
    charts.push(entry);
    return entry.instance;
  }

  function icons(scope) {
    if (!window.lucide) return;
    window.lucide.createIcons({
      root: scope || document,
      attrs: { "stroke-width": 1.75, "aria-hidden": "true" },
    });
  }

  /**
   * [data-ao-tabs] holds button.ao-tab[data-ao-tab="key"]; each key's panel is the
   * [data-ao-panel="key"] inside the closest [data-ao-tabs-scope], or the page.
   */
  function tabs(scope) {
    (scope || document).querySelectorAll("[data-ao-tabs]").forEach(function (group) {
      var area = group.closest("[data-ao-tabs-scope]") || document;
      var buttons = group.querySelectorAll("[data-ao-tab]");
      function select(key) {
        buttons.forEach(function (button) {
          button.setAttribute("aria-selected", String(button.getAttribute("data-ao-tab") === key));
        });
        area.querySelectorAll("[data-ao-panel]").forEach(function (panel) {
          panel.hidden = panel.getAttribute("data-ao-panel") !== key;
        });
        charts.forEach(function (entry) {
          entry.instance.resize();
        });
      }
      group.setAttribute("role", "tablist");
      buttons.forEach(function (button) {
        button.setAttribute("role", "tab");
        button.addEventListener("click", function () {
          select(button.getAttribute("data-ao-tab"));
        });
      });
      var chosen = group.querySelector('[aria-selected="true"]') || buttons[0];
      if (chosen) select(chosen.getAttribute("data-ao-tab"));
    });
  }

  if (dark && dark.addEventListener) {
    dark.addEventListener("change", function () {
      applyChartDefaults();
      charts.forEach(function (entry) {
        entry.instance.destroy();
        entry.instance = new window.Chart(entry.element, entry.build());
      });
    });
  }

  /*
   * Icons a script adds after the page loaded. Only an element still waiting to
   * be drawn counts - Lucide's <svg> keeps its data-lucide, and drawing it again
   * would be a mutation that never settles - and only the part of the page that
   * changed is drawn, once per burst of changes.
   */
  var WAITING = ":not(svg)[data-lucide]";
  var changed = [];
  var drawSoon = null;

  function drawChanged() {
    var scopes = changed;
    changed = [];
    drawSoon = null;
    scopes.forEach(function (scope, i) {
      if (scopes.indexOf(scope) !== i || !scope.isConnected || !scope.querySelector(WAITING)) return;
      var inner = scopes.some(function (other) {
        return other !== scope && other.contains(scope);
      });
      if (!inner) icons(scope);
    });
  }

  function watchIcons() {
    if (!window.MutationObserver || !document.body) return;
    new window.MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          if (node.matches(WAITING)) {
            if (node.parentNode) changed.push(node.parentNode);
          } else if (node.querySelector(WAITING)) {
            changed.push(node);
          }
        });
      });
      if (!window.lucide) changed = [];
      else if (changed.length && drawSoon === null) drawSoon = window.setTimeout(drawChanged, 0);
    }).observe(document.body, { childList: true, subtree: true });
  }

  function ready() {
    if (!window.lucide && document.querySelector("[data-lucide]")) {
      console.warn("AO: <i data-lucide> needs lib/lucide-1.46.0.min.js, loaded before lib/agenticos-3.js.");
    }
    icons();
    tabs();
    watchIcons();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();

  /**
   * The data bridge's agenticos.onData, looked up when called: the platform adds
   * the bridge when it serves the page, and a page opened any other way has none.
   */
  function onData(render) {
    var bridge = window.agenticos;
    if (!bridge || typeof bridge.onData !== "function") {
      throw new Error("AO.onData: this page has no data bridge - it is added when the page is served as an artifact.");
    }
    return bridge.onData(render);
  }

  var WORDS = {
    loading: "Loading…",
    unavailable: "No data available.",
    empty: "Nothing to show.",
    truncated: "Showing the first {count} records.",
    filtersDropped: "A filter of this view no longer applies, so the list may include more than it should.",
    yes: "Yes",
    no: "No",
  };

  var TONES = { success: true, warning: true, danger: true, info: true, outline: true };
  var NUMERIC = { number: true, integer: true, rating: true, date: true, datetime: true };
  var ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

  function own(map, key) {
    return map !== null && typeof map === "object" && Object.prototype.hasOwnProperty.call(map, key);
  }

  function tag(name, className, text) {
    var node = document.createElement(name);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function when(value, type) {
    var date = new Date(value);
    if (typeof value === "boolean" || isNaN(date.getTime())) return String(value);
    // A day with no time is that day everywhere, not midnight UTC in the reader's zone.
    if (typeof value === "string" && ISO_DAY.test(value)) return format.date(date, { dateStyle: "medium", timeZone: "UTC" });
    return format.date(date, type === "datetime" ? { dateStyle: "medium", timeStyle: "short" } : undefined);
  }

  function labelOf(item) {
    if (item !== null && typeof item === "object") return own(item, "label") ? String(item.label) : "";
    return String(item);
  }

  function written(value, type, words) {
    if (value === null || value === undefined) return "";
    if (Array.isArray(value)) return value.map(labelOf).join(", ");
    if (typeof value === "boolean") return value ? words.yes : words.no;
    if (typeof value === "number" && (type === "number" || type === "integer" || type === "rating")) {
      return format.number(value);
    }
    if (type === "date" || type === "datetime") return when(value, type);
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function badge(value, tones) {
    var tone = own(tones, value) ? tones[value] : null;
    var className = "ao-badge" + (own(TONES, tone) ? " ao-badge-" + tone : "");
    return tag("span", className, String(value));
  }

  function fill(template, values) {
    return String(template).replace(/\{(\w+)\}/g, function (whole, key) {
      return own(values, key) ? String(values[key]) : whole;
    });
  }

  /**
   * One bound view's records as a finished table in `target` (an element or a
   * selector), drawn again from scratch on every call:
   *
   *   agenticos.onData(function (data) { AO.records("#tickets", data.tickets); });
   *
   * With no binding yet it draws a loading line; an `unavailable` binding and an
   * empty one draw a message; a cut list and a dropped filter add a note. Columns
   * are the binding's fields in order, headed by their labels; a number or a date
   * is right-aligned and formatted for the page's language, a single or multiple
   * choice is a badge. Every value is written as text, never as markup.
   *
   * `options`: `columns` (field names, in order), `labels` ({field: heading}),
   * `badges` ({field: {value: "success" | "warning" | "danger" | "info" |
   * "outline"}}), `format` ({field: function (value, record) -> string}) and
   * `text`, the words for the states in the reader's language: `loading`,
   * `unavailable`, `empty`, `truncated` ("{count}" is the number shown),
   * `filtersDropped`, `yes`, `no`. Returns the table, or null for a state.
   */
  function records(target, binding, options) {
    var host = typeof target === "string" ? document.querySelector(target) : target;
    if (!host) throw new Error("AO.records: nothing on the page matches " + String(target) + ".");
    var opts = options || {};
    var words = Object.assign({}, WORDS, opts.text);
    var wrap = host.classList.contains("ao-table-wrap") ? host : tag("div", "ao-table-wrap");

    host.replaceChildren();
    if (wrap !== host) host.append(wrap);
    host.removeAttribute("aria-busy");

    function notes() {
      if (binding.truncated) host.append(tag("p", "ao-note", fill(words.truncated, { count: binding.count })));
      if (binding.filters_dropped) host.append(tag("p", "ao-note", words.filtersDropped));
    }

    if (!binding) {
      host.setAttribute("aria-busy", "true");
      wrap.append(tag("div", "ao-loading", words.loading));
      return null;
    }
    if (binding.status !== "ok") {
      wrap.append(tag("div", "ao-empty", words.unavailable));
      return null;
    }
    var rows = Array.isArray(binding.records) ? binding.records : [];
    if (!rows.length) {
      wrap.append(tag("div", "ao-empty", words.empty));
      notes();
      return null;
    }

    var fields = binding.fields && typeof binding.fields === "object" ? binding.fields : {};
    var columns = opts.columns;
    if (!columns) {
      columns = Object.keys(fields).filter(function (name) {
        var state = (fields[name] || {}).state;
        return state !== "missing" && state !== "archived";
      });
      if (!columns.length) {
        columns = Object.keys(rows[0]).filter(function (name) {
          return name !== "id";
        });
      }
    }

    var table = tag("table", "ao-table");
    var head = table.createTHead().insertRow();
    var body = table.createTBody();
    var described = columns.map(function (name) {
      return own(fields, name) && fields[name] ? fields[name] : {};
    });
    var types = described.map(function (field) {
      return field.type;
    });
    columns.forEach(function (name, i) {
      var heading = own(opts.labels, name) ? opts.labels[name] : described[i].label || name;
      head.append(tag("th", own(NUMERIC, types[i]) ? "ao-num" : "", String(heading)));
    });
    rows.forEach(function (record) {
      var row = body.insertRow();
      columns.forEach(function (name, i) {
        var type = types[i];
        var value = own(record, name) ? record[name] : null;
        var cell = row.insertCell();
        if (own(opts.format, name)) {
          cell.textContent = String(opts.format[name](value, record));
        } else if ((type === "single_select" || type === "multi_select") && value !== null && value !== "") {
          (Array.isArray(value) ? value : [value]).forEach(function (item, n) {
            if (n) cell.append(" ");
            cell.append(badge(item, own(opts.badges, name) ? opts.badges[name] : null));
          });
        } else {
          cell.textContent = written(value, type, words);
        }
        if (own(NUMERIC, type)) cell.className = "ao-num";
        else if (i === 0 && type !== "single_select" && type !== "multi_select") cell.className = "ao-strong";
      });
    });
    wrap.append(table);
    notes();
    return table;
  }

  window.AO = {
    chart: chart,
    color: color,
    format: format,
    icons: icons,
    onData: onData,
    records: records,
    series: series,
    tabs: tabs,
  };
})();
