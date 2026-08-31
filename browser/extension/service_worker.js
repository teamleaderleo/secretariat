const HOST_NAME = "com.secretariat.browser";
const PROTOCOL_VERSION = 1;
const ALIAS = /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) {
    sendResponse({ ok: false, error: "untrusted sender" });
    return false;
  }
  handleMessage(message)
    .then(sendResponse)
    .catch(() => sendResponse({ ok: false, error: "Secretariat browser request failed" }));
  return true;
});

async function handleMessage(message) {
  if (!message || typeof message !== "object") {
    return { ok: false, error: "invalid request" };
  }
  if (message.action === "candidates") {
    const tab = await activeHttpTab();
    const origin = canonicalOrigin(tab.url);
    const response = await nativeRequest("match", { origin });
    if (!response.ok || !Array.isArray(response.credentials)) {
      return { ok: false, error: nativeError(response) };
    }
    return {
      ok: true,
      origin,
      credentials: response.credentials.map((item) => ({
        alias: String(item.alias || ""),
        title: String(item.title || ""),
        provider: String(item.provider || ""),
        home_type: String(item.home_type || "")
      }))
    };
  }
  if (message.action === "fill") {
    if (typeof message.alias !== "string" || !ALIAS.test(message.alias)) {
      return { ok: false, error: "invalid credential alias" };
    }
    const tab = await activeHttpTab();
    const origin = canonicalOrigin(tab.url);
    const response = await nativeRequest("get", { origin, alias: message.alias });
    if (!response.ok || typeof response.password !== "string" || response.password.length === 0) {
      return { ok: false, error: nativeError(response) };
    }
    const password = response.password;
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: fillPasswordField,
      args: [password]
    });
    const result = results && results[0] ? results[0].result : null;
    return result && result.ok
      ? { ok: true }
      : { ok: false, error: result && result.error ? result.error : "password field was not filled" };
  }
  if (message.action === "status") {
    const response = await nativeRequest("status", {});
    return response.ok
      ? { ok: true, capabilities: response.capabilities || {} }
      : { ok: false, error: nativeError(response) };
  }
  return { ok: false, error: "unsupported request" };
}

async function activeHttpTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab || typeof tab.id !== "number" || typeof tab.url !== "string") {
    throw new Error("active tab is unavailable");
  }
  canonicalOrigin(tab.url);
  return tab;
}

function canonicalOrigin(value) {
  const parsed = new URL(value);
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new Error("unsupported page scheme");
  }
  return parsed.origin;
}

async function nativeRequest(action, payload) {
  const request = {
    version: PROTOCOL_VERSION,
    request_id: crypto.randomUUID(),
    action,
    ...payload
  };
  return await chrome.runtime.sendNativeMessage(HOST_NAME, request);
}

function nativeError(response) {
  if (response && response.error && typeof response.error.message === "string") {
    return response.error.message;
  }
  return "Secretariat native host rejected the request";
}

function fillPasswordField(password) {
  const visiblePasswordInputs = [...document.querySelectorAll('input[type="password"]')].filter((element) => {
    if (!(element instanceof HTMLInputElement) || element.disabled || element.readOnly) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  });

  let target = null;
  if (document.activeElement instanceof HTMLInputElement && document.activeElement.type === "password") {
    target = visiblePasswordInputs.includes(document.activeElement) ? document.activeElement : null;
  }
  if (!target && visiblePasswordInputs.length === 1) {
    target = visiblePasswordInputs[0];
  }
  if (!target) {
    return { ok: false, error: "focus a password field, or leave exactly one visible password field" };
  }

  const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  if (!descriptor || typeof descriptor.set !== "function") {
    return { ok: false, error: "password field setter is unavailable" };
  }
  descriptor.set.call(target, password);
  target.dispatchEvent(new Event("input", { bubbles: true }));
  target.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true };
}
