import { nativeMessagingError } from "./native_error.mjs";
import { sendNativeRequest } from "./native_request.mjs";
import { capturePasswordField } from "./password_capture.mjs";
import { fillLoginFields } from "./password_fill.mjs";

const HOST_NAME = "com.secretariat.browser";
const PROTOCOL_VERSION = 1;
const MAX_BROWSER_PASSWORD_CHARS = 16_384;
const ALIAS = /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) {
    sendResponse({ ok: false, error: "untrusted sender" });
    return false;
  }
  handleMessage(message)
    .then(sendResponse)
    .catch((error) => sendResponse({ ok: false, error: nativeMessagingError(error) }));
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
        username: typeof item.username === "string" ? item.username : null,
        provider: String(item.provider || ""),
        home_type: String(item.home_type || ""),
        fillable: item.fillable === true,
        updatable: item.updatable === true,
        unavailable_reason: typeof item.unavailable_reason === "string" ? item.unavailable_reason : null
      }))
    };
  }
  if (message.action === "fill") {
    if (!validAlias(message.alias)) {
      return { ok: false, error: "invalid credential alias" };
    }
    const tab = await activeHttpTab();
    const origin = canonicalOrigin(tab.url);
    const response = await nativeRequest("get", { origin, alias: message.alias });
    if (!response.ok || typeof response.password !== "string" || response.password.length === 0) {
      return { ok: false, error: nativeError(response) };
    }
    const username = response.username == null ? null : response.username;
    if (
      username !== null
      && (
        typeof username !== "string"
        || username.length === 0
        || username.length > 512
        || /[\u0000-\u001f\u007f]/.test(username)
      )
    ) {
      return { ok: false, error: "native host returned invalid account metadata" };
    }

    const currentTab = await chrome.tabs.get(tab.id);
    if (typeof currentTab.url !== "string" || canonicalOrigin(currentTab.url) !== origin) {
      return { ok: false, error: "page origin changed before fill" };
    }

    const password = response.password;
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: fillLoginFields,
      args: [username, password]
    });
    const result = results && results[0] ? results[0].result : null;
    return result && result.ok
      ? { ok: true, username_filled: result.username_filled === true }
      : { ok: false, error: result && result.error ? result.error : "password field was not filled" };
  }
  if (message.action === "update") {
    if (!validAlias(message.alias)) {
      return { ok: false, error: "invalid credential alias" };
    }
    const tab = await activeHttpTab();
    const origin = canonicalOrigin(tab.url);
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: capturePasswordField
    });
    const result = results && results[0] ? results[0].result : null;
    if (!result || !result.ok) {
      return {
        ok: false,
        error: result && result.error ? result.error : "password field could not be read"
      };
    }
    if (
      typeof result.password !== "string"
      || result.password.length === 0
      || result.password.length > MAX_BROWSER_PASSWORD_CHARS
    ) {
      return { ok: false, error: "password field value is outside the reviewed browser bound" };
    }

    const currentTab = await chrome.tabs.get(tab.id);
    if (typeof currentTab.url !== "string" || canonicalOrigin(currentTab.url) !== origin) {
      return { ok: false, error: "page origin changed before update" };
    }

    let password = result.password;
    try {
      const response = await nativeRequest("update", {
        origin,
        alias: message.alias,
        password
      });
      return response.ok && response.updated === true
        ? { ok: true }
        : { ok: false, error: nativeError(response) };
    } finally {
      password = null;
    }
  }
  if (message.action === "status") {
    const response = await nativeRequest("status", {});
    return response.ok
      ? { ok: true, capabilities: response.capabilities || {} }
      : { ok: false, error: nativeError(response) };
  }
  return { ok: false, error: "unsupported request" };
}

function validAlias(value) {
  return typeof value === "string" && ALIAS.test(value);
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
  return await sendNativeRequest(chrome.runtime, HOST_NAME, request);
}

function nativeError(response) {
  if (response && response.error && typeof response.error.message === "string") {
    return response.error.message;
  }
  return "Secretariat native host rejected the request";
}
