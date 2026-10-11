/*
 * AgenticOS page kit, version 2 - served to published artifacts, as `window.AO`.
 *
 * The behaviour half of agenticos-2.css. Load it after the libraries it
 * dresses and before the page's own script:
 *
 *   <script src="lib/chart-4.5.1.umd.min.js"></script>
 *   <script src="lib/lucide-1.46.0.min.js"></script>
 *   <script src="lib/agenticos-2.js"></script>
 *
 * What it does on its own: gives Chart.js the console's fonts, grid, tooltip and
 * series colours; turns every <i data-lucide="name"> into its icon; wires every
 * [data-ao-tabs] group to its panels. What it offers: AO.chart, AO.format,
 * AO.series, AO.color, AO.icons, AO.tabs.
 *
 * Versioned like the stylesheet: a change that would alter an existing page is
 * agenticos-3.js.
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

  function ready() {
    icons();
    tabs();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();

  window.AO = {
    chart: chart,
    color: color,
    format: format,
    icons: icons,
    series: series,
    tabs: tabs,
  };
})();
