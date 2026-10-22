function agenticosDataBridge(window, document, config) {
  "use strict";
  // The page side of a bound artifact's data (#1974). The console fetches the
  // bindings as the viewer and posts them here; this page never reaches the
  // network. `config` is `{n, live, names}`: the nonce the console matches its
  // replies on, whether to ask at all, and the binding names the page declares.
  // Timers go through `window` so a test can drive them.
  var FIRST_RESEND_MS = 100;
  var LONGEST_RESEND_MS = 2000;
  var GIVE_UP_MS = 10000;

  var parent = window.parent;
  var names = config.names;
  var n = config.n;
  var asking = config.live === true && parent !== window;
  var listeners = [];
  var subscribes = false;
  var answered = false;
  var last = null;
  var settle;
  var resendTimer = null;
  var giveUpTimer = null;
  var delay = FIRST_RESEND_MS;

  var data = new Promise(function (resolve) { settle = resolve; });

  function unavailable() {
    return {
      status: "unavailable", records: [], fields: {}, truncated: false,
      limit: null, count: 0
    };
  }

  // `defineProperty` rather than assignment, so a name such as `__proto__` is
  // an own key of the answer and never its prototype.
  function put(target, name, value) {
    Object.defineProperty(target, name, {
      value: value, enumerable: true, writable: true, configurable: true
    });
  }

  function shaped(bindings) {
    var out = {};
    var given = bindings !== null && typeof bindings === "object" ? bindings : {};
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      var value = Object.prototype.hasOwnProperty.call(given, name) ? given[name] : null;
      put(out, name, value !== null && typeof value === "object" ? value : unavailable());
    }
    return out;
  }

  function deliver(value) {
    last = value;
    settle(value); // a no-op after the first: `data` is the first answer
    for (var i = 0; i < listeners.length; i++) listeners[i](value);
  }

  function ready() {
    parent.postMessage({ type: "agenticos:ready", n: n, subscribes: subscribes }, "*");
  }

  function stopAsking() {
    if (resendTimer !== null) window.clearTimeout(resendTimer);
    if (giveUpTimer !== null) window.clearTimeout(giveUpTimer);
    resendTimer = null;
    giveUpTimer = null;
  }

  function resend() {
    ready();
    resendTimer = window.setTimeout(resend, delay);
    delay = Math.min(delay * 2, LONGEST_RESEND_MS);
  }

  function onData(fn) {
    listeners.push(fn);
    if (!subscribes) {
      subscribes = true;
      // Once, so the console learns it may refresh this page in place.
      if (asking) ready();
    }
    if (last !== null) fn(last);
  }

  window.agenticos = { data: data, onData: onData };

  if (!asking) {
    deliver(shaped({}));
    return;
  }

  window.addEventListener("message", function (event) {
    var message = event.data;
    if (event.source !== parent || message === null || typeof message !== "object") return;
    if (message.type !== "agenticos:data" || message.n !== n) return;
    if (!answered) {
      answered = true;
      stopAsking();
    }
    deliver(shaped(message.bindings));
  });

  // The console forgets the handshake each time the frame loads, and that load
  // comes after this script asked - often after it was answered and stopped.
  // One more ready once the page has loaded tells the console again whether it
  // listens. Once, without restarting the backoff; and also after the give-up,
  // since a late answer is still delivered. Not when the page had loaded before
  // this ran: then no frame load follows this ready.
  if (document.readyState !== "complete") {
    var saidLoaded = false;
    window.addEventListener("load", function () {
      if (saidLoaded) return;
      saidLoaded = true;
      ready();
    });
  }

  giveUpTimer = window.setTimeout(function () {
    stopAsking();
    if (!answered) deliver(shaped({}));
  }, GIVE_UP_MS);
  resend();
}
