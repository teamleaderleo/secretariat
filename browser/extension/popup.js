const origin = document.querySelector("#origin");
const message = document.querySelector("#message");
const credentials = document.querySelector("#credentials");

loadCandidates();

async function loadCandidates() {
  try {
    const response = await chrome.runtime.sendMessage({ action: "candidates" });
    if (!response || !response.ok) {
      showMessage(response && response.error ? response.error : "Secretariat is unavailable");
      return;
    }
    origin.textContent = response.origin || "";
    credentials.replaceChildren();
    if (!Array.isArray(response.credentials) || response.credentials.length === 0) {
      showMessage("No password credential is authorized for this page.");
      return;
    }
    showMessage("Choose a credential action.");
    for (const credential of response.credentials) {
      credentials.appendChild(credentialCard(credential));
    }
  } catch {
    showMessage("Secretariat is unavailable.");
  }
}

function credentialCard(credential) {
  const card = document.createElement("section");
  card.className = "credential";

  const title = document.createElement("strong");
  title.textContent = credential.title || credential.alias || "Credential";
  const detail = document.createElement("span");
  const parts = [credential.username, credential.provider, credential.home_type].filter(Boolean);
  if (credential.fillable !== true && credential.updatable !== true) {
    parts.push(unavailableLabel(credential.unavailable_reason));
  }
  detail.textContent = parts.join(" · ");

  const actions = document.createElement("div");
  actions.className = "actions";

  const fill = actionButton("Fill", credential.fillable === true);
  if (credential.fillable === true) {
    fill.addEventListener("click", () => fillCredential(credential, actions));
  }
  actions.appendChild(fill);

  const update = actionButton("Update saved password", credential.updatable === true);
  if (credential.updatable === true) {
    update.addEventListener("click", () => updateCredential(credential, actions));
  }
  actions.appendChild(update);

  card.append(title, detail, actions);
  return card;
}

function actionButton(label, enabled) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.disabled = !enabled;
  return button;
}

async function fillCredential(credential, actions) {
  setActionsDisabled(actions, true);
  showMessage("Filling…");
  try {
    const response = await chrome.runtime.sendMessage({ action: "fill", alias: credential.alias });
    if (!response || !response.ok) {
      showMessage(response && response.error ? response.error : "Password field was not filled.");
      setActionsDisabled(actions, false);
      return;
    }
    showMessage(response.username_filled ? "Username and password filled." : "Password filled.");
    window.close();
  } catch {
    showMessage("Password field was not filled.");
    setActionsDisabled(actions, false);
  }
}

async function updateCredential(credential, actions) {
  const label = credential.title || credential.alias || "this credential";
  if (!window.confirm(`Replace Secretariat's saved password for ${label} with the selected page field?`)) {
    return;
  }
  setActionsDisabled(actions, true);
  showMessage("Updating saved password…");
  try {
    const response = await chrome.runtime.sendMessage({ action: "update", alias: credential.alias });
    if (!response || !response.ok) {
      showMessage(response && response.error ? response.error : "Saved password was not updated.");
      setActionsDisabled(actions, false);
      return;
    }
    showMessage("Saved password updated.");
    window.close();
  } catch {
    showMessage("Saved password was not updated.");
    setActionsDisabled(actions, false);
  }
}

function setActionsDisabled(actions, disabled) {
  for (const button of actions.querySelectorAll("button")) {
    button.disabled = disabled;
  }
}

function unavailableLabel(reason) {
  if (reason === "secret_service_helper_missing") return "Secret Service helper missing";
  if (reason === "background_unlock_unavailable") return "background unlock unavailable";
  return "unavailable";
}

function showMessage(value) {
  message.textContent = value;
}
