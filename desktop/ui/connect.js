const { invoke } = window.__TAURI__.core;

const DEFAULT_SERVER = "http://localhost:3000";

const form = document.getElementById("connect");
const input = document.getElementById("server");
const error = document.getElementById("error");
const submit = form.querySelector("button");

function showError(message) {
  error.textContent = String(message);
  error.hidden = false;
}

invoke("server_url")
  .then((url) => {
    input.value = url ?? DEFAULT_SERVER;
  })
  .catch(showError);

invoke("startup_notice")
  .then((notice) => {
    if (notice) showError(notice);
  })
  .catch(showError);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.hidden = true;
  submit.disabled = true;
  try {
    await invoke("connect", { url: input.value });
  } catch (message) {
    showError(message);
    submit.disabled = false;
  }
});
