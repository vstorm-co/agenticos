/** @typedef {(command: string, args?: Record<string, string>) => Promise<unknown>} Invoke */

const VIEWS = {
  no_docker: {
    title: "Prepare this computer",
    message:
      "AgenticOS will install what it needs to run on this computer. Approve any system prompts that appear.",
    actions: ["docker"],
  },
  docker_stopped: {
    title: "Start your local workspace",
    message: "AgenticOS will start everything it needs for you.",
    actions: ["open-docker"],
  },
  running: {
    title: "Your local workspace is ready",
    message:
      "AgenticOS is running on this computer. Connect to sign in and finish setting up desktop features.",
    actions: ["use", "create"],
  },
  ready: {
    title: "Ready to create your workspace",
    message:
      "Create an instance for your organization and choose its owner account.",
    actions: ["create"],
  },
};

/**
 * Local setup keeps its status card mounted while probing and connecting.
 * @param {HTMLElement} root
 * @param {Invoke} invoke
 * @param {(message: unknown) => void} report
 * @returns {(() => Promise<void>) & { progress: (payload: unknown) => void, resume: () => Promise<void>, prepare: () => Promise<void> }}
 */
export function localComputerStep(root, invoke, report) {
  const card = root.querySelector("[data-local-instance]");
  const title = root.querySelector("[data-local-title]");
  const message = root.querySelector("[data-local-message]");
  const actions = root.querySelector("[data-local-actions]");
  const form = root.querySelector("form");
  const list = root.querySelector("[data-instance-list]");
  const instanceError = root.querySelector("[data-instance-error]");
  const overview = root.querySelector("[data-local-overview]");
  const create = root.querySelector("[data-local-create]");
  const heading = root.querySelector("[data-local-heading]");
  const lead = root.querySelector("[data-local-lead]");
  let instances = [];
  let updating = false;
  const updateProgress = root.querySelector("[data-local-update-progress]");
  const updateStatus = root.querySelector("[data-local-update-status]");
  /** @param {string} text @returns {HTMLSpanElement} */
  function label(text) {
    const span = document.createElement("span");
    span.dataset.onboardingCopy = "";
    span.textContent = text;
    return span;
  }
  function showOverview() {
    root.dataset.view = "overview";
    overview.hidden = false;
    create.hidden = true;
    form.hidden = true;
    heading.textContent = "AgenticOS on this computer";
    lead.textContent = "A local workspace, managed from your menu bar.";
  }
  form
    .querySelector('[data-action="cancel-create"]')
    .addEventListener("click", () => {
      showOverview();
      actions
        .querySelector('[data-action="create"]')
        ?.focus({ preventScroll: true });
    });
  function showForm(instance) {
    root.dataset.view = "create";
    overview.hidden = true;
    create.hidden = false;
    form.hidden = false;
    heading.textContent = instance
      ? "Finish setting up your instance"
      : "Create a local instance";
    lead.textContent = "Your own workspace, running on this computer.";
    form.querySelector("[name=instance-id]").value = instance?.id ?? "";
    form.querySelector("[name=instance-name]").value = instance?.name ?? "";
    form.querySelector("[name=instance-name]").focus();
  }
  async function refreshInstances(request) {
    try {
      const answer = await invoke("local_instances");
      if (request !== generation || root.hidden) return;
      if (
        !Array.isArray(answer) ||
        answer.some(
          (row) =>
            !row ||
            typeof row.id !== "string" ||
            typeof row.name !== "string" ||
            typeof row.url !== "string" ||
            typeof row.installed !== "boolean" ||
            typeof row.running !== "boolean" ||
            (row.version != null && typeof row.version !== "string") ||
            (row.version_error != null &&
              typeof row.version_error !== "string") ||
            (row.target_version !== undefined &&
              typeof row.target_version !== "string") ||
            (row.can_update !== undefined &&
              typeof row.can_update !== "boolean"),
        )
      )
        throw new Error("The app could not read its local instances.");
      instances = answer;
      list.replaceChildren();
      for (const instance of instances) {
        const row = document.createElement("div");
        row.className = "instance-row";
        const description = document.createElement("div");
        const name = document.createElement("strong");
        name.textContent = instance.name;
        const hint = document.createElement("p");
        hint.textContent = `${instance.url} · ${!instance.installed ? "Setup unfinished" : instance.running ? "Running" : "Stopped"}`;
        description.append(name, hint);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = !instance.installed
          ? "Finish setup"
          : instance.running
            ? "Connect"
            : "Start and connect";
        button.dataset.instance = instance.id;
        row.append(description, button);
        if (instance.installed && typeof instance.target_version === "string") {
          const versions = document.createElement("p");
          if (instance.version) {
            versions.append(
              label("Workspace"),
              ` ${instance.version} · `,
              label("Update target"),
              ` ${instance.target_version}`,
            );
          } else {
            versions.append(
              label("Workspace version unavailable; target"),
              ` ${instance.target_version}`,
            );
          }
          description.append(versions);
          if (typeof instance.version_error === "string") {
            const error = document.createElement("p");
            error.className = "error";
            error.textContent = instance.version_error;
            description.append(error);
          }
          if (instance.can_update === true) {
            const update = document.createElement("button");
            update.type = "button";
            update.className = "secondary";
            update.dataset.onboardingCopy = "";
            update.textContent =
              instance.version === instance.target_version
                ? "Reapply workspace update"
                : "Update local workspace";
            update.dataset.updateInstance = instance.id;
            row.append(update);
          }
        }
        list.append(row);
      }
      list.hidden = instances.length === 0;
      instanceError.hidden = true;
    } catch (error) {
      if (request !== generation || root.hidden) return;
      instanceError.hidden = false;
      instanceError.textContent = String(error);
    }
  }
  list.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element) || connecting || updating) return;
    const button = event.target.closest("[data-update-instance]");
    const instance = instances.find(
      (item) => item.id === button?.dataset.updateInstance,
    );
    if (!instance?.installed || instance.can_update !== true) return;
    updating = true;
    instanceError.hidden = true;
    updateProgress.hidden = false;
    updateStatus.textContent = "Waiting for update confirmation…";
    for (const control of root.querySelectorAll("button"))
      control.disabled = true;
    try {
      const updated = await invoke("update_local", { instanceId: instance.id });
      if (typeof updated !== "boolean")
        throw new Error("The app could not read the update result.");
      await refreshInstances(generation);
      updateStatus.textContent = updated
        ? "Workspace updated. Connect to continue."
        : "Workspace update cancelled.";
    } catch (error) {
      instanceError.hidden = false;
      instanceError.textContent = String(error);
      updateStatus.textContent =
        "Workspace update failed. Resolve the error and retry.";
    } finally {
      updating = false;
      updateProgress.hidden = true;
      for (const control of root.querySelectorAll("button"))
        control.disabled = false;
      const next =
        list.querySelector(`[data-update-instance="${instance.id}"]`) ??
        list.querySelector(`[data-instance="${instance.id}"]`);
      next?.focus();
    }
  });
  list.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest("[data-instance]");
    const instance = instances.find(
      (item) => item.id === button?.dataset.instance,
    );
    if (!instance || connecting || updating) return;
    if (!instance.installed) {
      showForm(instance);
      return;
    }
    connecting = true;
    root.inert = true;
    button.disabled = true;
    button.textContent = "Connecting…";
    try {
      await invoke("use_local", { instanceId: instance.id });
    } catch (error) {
      instanceError.hidden = false;
      instanceError.textContent = String(error);
      connecting = false;
      root.inert = false;
      button.disabled = false;
      button.textContent = "Retry connection";
    }
  });
  let generation = 0;
  let connecting = false;
  let preparing = false;
  function setBusy(busy) {
    card.setAttribute("aria-busy", String(busy));
  }
  function showActions(visible) {
    actions.hidden = false;
    const primary = ["use", "create", "docker", "open-docker", "check"].find(
      (action) => visible.includes(action),
    );
    for (const button of actions.querySelectorAll("[data-action]")) {
      button.hidden = !visible.includes(button.dataset.action);
      button.classList.toggle("primary", button.dataset.action === primary);
      button.classList.toggle("secondary", button.dataset.action !== primary);
    }
  }
  async function refresh() {
    if (updating) return;
    const request = ++generation;
    showOverview();
    card.dataset.state = "checking";
    setBusy(true);
    title.textContent = "Checking this computer";
    message.textContent = "Checking your local workspace…";
    showActions([]);
    form.hidden = true;
    try {
      const status = await invoke("local_status");
      if (request !== generation || root.hidden) return;
      if (typeof status !== "string" || !Object.hasOwn(VIEWS, status))
        throw new Error("The app could not read this computer's status.");
      await refreshInstances(request);
      if (request !== generation || root.hidden) return;
      const view = VIEWS[status];
      card.dataset.state = status;
      title.textContent = view.title;
      message.textContent = view.message;
      showActions(view.actions);
    } catch (error) {
      if (request !== generation || root.hidden) return;
      card.dataset.state = "error";
      title.textContent = "Could not check this computer";
      message.textContent = String(error);
      showActions(["check"]);
    } finally {
      if (request === generation) setBusy(false);
    }
  }
  async function prepareRuntime(action) {
    if (preparing) return;
    preparing = true;
    showActions([]);
    setBusy(true);
    title.textContent =
      action === "docker"
        ? "Preparing this computer"
        : "Starting your workspace";
    message.textContent =
      "Approve any system installation or first-run prompts. AgenticOS will continue automatically.";
    try {
      await invoke(action === "docker" ? "download_docker" : "open_docker");
      await refresh();
      if (
        card.dataset.state === "ready" &&
        instances.length === 0 &&
        instanceError.hidden
      )
        showForm(null);
      else if (card.dataset.state === "no_docker") {
        message.textContent =
          "Complete the runtime installation, then choose Check again to continue.";
        showActions(["docker", "check"]);
      }
    } catch (error) {
      title.textContent = "Setup needs your attention";
      message.textContent = String(error);
      showActions(
        action === "open-docker"
          ? ["open-docker", "docker", "check"]
          : ["docker", "check"],
      );
      report(error);
    } finally {
      preparing = false;
      setBusy(false);
    }
  }
  actions.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest("[data-action]");
    const action = button?.dataset.action;
    if (action === "check") await refresh();
    if (action === "create") showForm(null);
    if (action === "docker" || action === "open-docker")
      await prepareRuntime(action);
    if (action !== "use" || connecting) return;
    connecting = true;
    root.inert = true;
    button.disabled = true;
    root.querySelector("[data-go]").disabled = true;
    button.dataset.busy = "true";
    button.textContent = "Connecting…";
    setBusy(true);
    try {
      await invoke("use_local");
    } catch (error) {
      message.textContent = String(error);
      connecting = false;
      root.inert = false;
      button.disabled = false;
      root.querySelector("[data-go]").disabled = false;
      delete button.dataset.busy;
      button.textContent = "Connect and continue";
      setBusy(false);
    }
  });
  refresh.progress = (payload) => {
    if (!updating) return;
    const labels = {
      download: "Downloading workspace images…",
      backup: "Backing up the database, files and keys…",
      restart: "Restarting the workspace and checking health…",
    };
    if (
      typeof payload === "object" &&
      payload !== null &&
      "step" in payload &&
      typeof payload.step === "string" &&
      Object.hasOwn(labels, payload.step) &&
      updateStatus.textContent !== labels[payload.step]
    )
      updateStatus.textContent = labels[payload.step];
  };
  refresh.prepare = () => prepareRuntime("docker");
  refresh.resume = async () => {
    ++generation;
    showOverview();
    connecting = true;
    setBusy(true);
    showActions([]);
    list.hidden = true;
    title.textContent = "Starting AgenticOS";
    message.textContent =
      "Opening your saved workspace. This may take a few minutes.";
    try {
      const resumed = await invoke("resume_local");
      if (resumed === false) {
        connecting = false;
        await refresh();
      } else if (resumed !== true) {
        throw new Error("The app could not read its workspace startup result.");
      }
    } catch (error) {
      connecting = false;
      await refresh();
      title.textContent = "Your workspace could not start";
      message.textContent = String(error);
    } finally {
      setBusy(false);
    }
  };
  return refresh;
}
