import { acceleratorOf, describe } from "./shortcut-recorder.js";

const { invoke } = window.__TAURI__.core;

const mac = navigator.platform.startsWith("Mac");
const form = document.getElementById("shortcuts");
const field = document.getElementById("screenshot");
const save = document.getElementById("save");
const clear = document.getElementById("clear");
const back = document.getElementById("back");
const error = document.getElementById("error");

let bound = null;
let recorded = null;

function showError(message) {
  error.textContent = String(message);
  error.hidden = false;
}

function show(accelerator) {
  field.value = describe(accelerator, mac);
  save.disabled = recorded === null || recorded === bound;
}

field.addEventListener("focus", () => {
  field.placeholder = "Press a combination…";
});

field.addEventListener("blur", () => {
  field.placeholder = "Not bound";
  if (recorded === null) show(bound);
});

field.addEventListener("keydown", (event) => {
  event.preventDefault();
  if (event.code === "Escape") {
    recorded = null;
    show(bound);
    field.blur();
    return;
  }
  const accelerator = acceleratorOf(event);
  if (!accelerator) return;
  recorded = accelerator;
  error.hidden = true;
  show(recorded);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (recorded === null) return;
  try {
    bound = await invoke("set_screenshot_shortcut", { accelerator: recorded });
    recorded = null;
    show(bound);
  } catch (message) {
    showError(message);
  }
});

clear.addEventListener("click", async () => {
  try {
    bound = await invoke("set_screenshot_shortcut", { accelerator: null });
    recorded = null;
    error.hidden = true;
    show(bound);
  } catch (message) {
    showError(message);
  }
});

back.addEventListener("click", (event) => {
  event.preventDefault();
  void invoke("back_to_console").catch(showError);
});

invoke("shortcuts")
  .then((shortcuts) => {
    bound = shortcuts.screenshot_chat;
    show(bound);
  })
  .catch(showError);
