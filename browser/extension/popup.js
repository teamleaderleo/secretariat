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
    showMessage("Choose an available credential to fill the password field.");
    for (const credential of response.credentials) {
      credentials.appendChild(credentialButton(credential));
    }
  } catch {
    showMessage("Secretariat is unavailable.");
  }
}

function credentialButton(credential) {
  const button = document.createElement("button");
  button.type = "button";
  const title = document.createElement("strong");
  title.textContent = credential.title || credential.alias || "Credential";
  const detail = document.createElement("span");
  const parts = [credential.username, credential.provider, credential.home_type].filter(Boolean);
  if (credential.fillable !== true) {
    parts.push(unavailableLabel(credential.unavailable_reason));
    button.disabled = true;
  }
  detail.textContent = parts.join(" · ");
  button.append(title, detail);
  if (credential.fillable === true) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      showMessage("Filling…");
      try {
        const response = await chrome.runtime.sendMessage({ action: "fill", alias: credential.alias });
        if (!response || !response.ok) {
          showMessage(response && response.error ? response.error : "Password field was not filled.");
          button.disabled = false;
          return;
        }
        showMessage(response.username_filled ? "Username and password filled." : "Password filled.");
        window.close();
      } catch {
        showMessage("Password field was not filled.");
        button.disabled = false;
      }
    });
  }
  return button;
}

function unavailableLabel(reason) {
  if (reason === "secret_service_helper_missing") return "Secret Service helper missing";
  if (reason === "background_unlock_unavailable") return "background unlock unavailable";
  return "unavailable";
}

function showMessage(value) {
  message.textContent = value;
}
