function agenticosDataBridge(window, document, config) {
  "use strict";
  // The page side of a bound artifact's data (#1974). The console fetches the
  // bindings as the viewer and posts them here; this page never reaches the
  // network. `config` is `{n, live, names, initial?}`: the nonce the console
  // matches its replies on, whether to ask at all, the binding names the page
  // declares and, for a page served with its data, `initial` - `[name, binding]`
  // pairs answered at load. Later answers (a refresh) are still posted. It also
  // carries `actions` (#1976): true only for the page viewer's own address, where
  // `run` may ask the console to start a declared workflow.
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

  // Actions: `run` posts a request, never a start. The console - which owns the
  // frame, the person and the version - decides, and answers with run events under
  // this nonce, from the parent only. Without `actions` it rejects before posting. Rejections are codes: `unavailable`,
  // `unknown_action`, `invalid_input` (no `problems` from here).
  var runnable = config.actions === true && parent !== window;
  var runs = {};
  var runListeners = [];
  var lastId = 0;

  function runResult(message) {
    return {
      status: String(message.status),
      output_text: typeof message.output_text === "string" ? message.output_text : null,
      output_structured:
        message.output_structured !== null && typeof message.output_structured === "object"
          ? message.output_structured : null,
      error_message: typeof message.error_message === "string" ? message.error_message : null,
      paused: message.paused === true,
      run_path: typeof message.run_path === "string" ? message.run_path : null
    };
  }

  function run(action, input) {
    if (!runnable) {
      return Promise.reject(new Error("unavailable"));
    }
    // Before this document has loaded the console cannot tell it from the one the
    // frame showed before it, whose request it may still be answering.
    if (document.readyState !== "complete") {
      return Promise.reject(new Error("not_ready"));
    }
    if (typeof action !== "string" || action === "") {
      return Promise.reject(new Error("unknown_action"));
    }
    var given = input === undefined ? {} : input;
    if (given === null || typeof given !== "object" || Array.isArray(given)) {
      return Promise.reject(new Error("invalid_input"));
    }
    lastId += 1;
    var id = "r" + lastId;
    return new Promise(function (resolve, reject) {
      runs[id] = { action: action, resolve: resolve, reject: reject };
      try {
        parent.postMessage(
          { type: "agenticos:run", n: n, id: id, action: action, input: given }, "*"
        );
      } catch (error) {
        delete runs[id];
        reject(new Error("invalid_input"));
      }
    });
  }

  function onRun(fn) {
    runListeners.push(fn);
    return function () {
      var at = runListeners.indexOf(fn);
      if (at !== -1) runListeners.splice(at, 1);
    };
  }

  if (runnable) {
    window.addEventListener("message", function (event) {
      var message = event.data;
      if (event.source !== parent || message === null || typeof message !== "object") return;
      if (message.type !== "agenticos:run-event" || message.n !== n) return;
      if (typeof message.id !== "string" || !Object.prototype.hasOwnProperty.call(runs, message.id)) return;
      var pending = runs[message.id];
      if (message.event === "rejected") {
        delete runs[message.id];
        var failure = new Error(typeof message.reason === "string" ? message.reason : "rejected");
        // `invalid_input` says what did not fit: [{field, kind}], as plain strings.
        if (Array.isArray(message.problems)) {
          failure.problems = message.problems.map(function (item) {
            return { field: String(item && item.field), kind: String(item && item.kind) };
          });
        }
        pending.reject(failure);
        return;
      }
      if (message.event !== "progress") return;
      var result = runResult(message);
      var progress = runResult(message);
      progress.id = message.id;
      progress.action = pending.action;
      progress.finished = message.finished === true;
      // `settled`: the console stopped following a paused run - resolve with its
      // last projection (paused, not finished) rather than never.
      var settled = progress.finished || message.settled === true;
      if (settled) delete runs[message.id];
      for (var k = 0; k < runListeners.length; k++) runListeners[k](progress);
      if (settled) pending.resolve(result);
    });
  }

  // Joined onto what the platform script already put there (`map`, `followUp`,
  // `canFollowUp`), which is a frozen object, so it is replaced rather than extended.
  window.agenticos = Object.freeze(
    Object.assign({}, window.agenticos, { data: data, onData: onData, run: run, onRun: onRun })
  );

  // Answered at load: the server wrote the data in, so there is nothing to wait
  // for. Names are only ever own keys of the answer (`put`), whatever they are.
  var injected = Array.isArray(config.initial);
  if (injected) {
    var given = {};
    for (var j = 0; j < config.initial.length; j++) {
      var pair = config.initial[j];
      if (Array.isArray(pair) && typeof pair[0] === "string") put(given, pair[0], pair[1]);
    }
    answered = true;
    deliver(shaped(given));
  } else if (!asking) {
    deliver(shaped({}));
  }
  if (!asking) return;

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

  if (injected) return;
  giveUpTimer = window.setTimeout(function () {
    stopAsking();
    if (!answered) deliver(shaped({}));
  }, GIVE_UP_MS);
  resend();
}
