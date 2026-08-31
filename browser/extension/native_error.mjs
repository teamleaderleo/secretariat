export function nativeMessagingError(error) {
  const message = typeof error === "string"
    ? error
    : error && typeof error.message === "string"
      ? error.message
      : "";
  if (/native messaging host.*not found/i.test(message)) {
    return "Secretariat native host is not installed for this browser";
  }
  if (/native messaging host.*forbidden/i.test(message)) {
    return "Secretariat native host does not authorize this extension";
  }
  if (/native host has exited/i.test(message)) {
    return "Secretariat native host stopped before replying";
  }
  if (/native messaging host/i.test(message)) {
    return "Secretariat native host is unavailable; check this browser's host registration";
  }
  return "Secretariat browser request failed";
}
