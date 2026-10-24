/**
 * The phone's first run: scan the code the console shows, or type the address.
 * Either way the console takes over from there, signed in or at its sign-in page.
 */

const { invoke } = window.__TAURI__.core;

const screens = [...document.querySelectorAll("[data-screen]")];
const welcomeError = document.querySelector('[data-screen="welcome"] .error');
const form = document.getElementById("address-form");
const field = document.getElementById("server");
const formError = form.querySelector(".error");

function show(name, focus = true) {
  for (const screen of screens) screen.hidden = screen.dataset.screen !== name;
  if (name === "address" && focus) field.focus();
}

function say(element, message) {
  element.textContent = String(message);
  element.hidden = false;
}

for (const button of document.querySelectorAll("[data-go]")) {
  button.addEventListener("click", () => show(button.dataset.go));
}

/** The camera, asked for once, with a way to the system settings if it was refused. */
async function scan() {
  const scanner = window.__TAURI__.barcodeScanner;
  if (!scanner) throw new Error("This device has no camera to scan with. Enter the address instead.");
  let permission = await scanner.checkPermissions();
  if (permission === "prompt" || permission === "prompt-with-rationale") {
    permission = await scanner.requestPermissions();
  }
  if (permission !== "granted") {
    await scanner.openAppSettings();
    throw new Error("Allow AgenticOS to use the camera, then scan again.");
  }
  const result = await scanner.scan({ windowed: false, formats: [scanner.Format.QRCode] });
  return result.content;
}

document.querySelector('[data-action="scan"]').addEventListener("click", async () => {
  welcomeError.hidden = true;
  try {
    const link = await scan();
    await invoke("pair_with", { link });
  } catch (message) {
    say(welcomeError, message instanceof Error ? message.message : message);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.hidden = true;
  const submit = form.querySelector(".filled");
  submit.disabled = true;
  try {
    await invoke("connect", { url: field.value });
  } catch (message) {
    say(formError, message);
    submit.disabled = false;
  }
});

Promise.all([invoke("server_url"), invoke("startup_notice")])
  .then(([url, notice]) => {
    if (url) field.value = url;
    if (notice) {
      show("address", false);
      say(formError, notice);
    }
  })
  .catch((message) => say(welcomeError, message));
