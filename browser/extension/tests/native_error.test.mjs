import assert from "node:assert/strict";
import test from "node:test";

import { nativeMessagingError } from "../native_error.mjs";

test("explains that the native host manifest is missing", () => {
  assert.equal(
    nativeMessagingError({ message: "Specified native messaging host not found." }),
    "Secretariat native host is not installed for this browser"
  );
});

test("explains that the extension origin is not authorized", () => {
  assert.equal(
    nativeMessagingError(new Error("Access to the specified native messaging host is forbidden.")),
    "Secretariat native host does not authorize this extension"
  );
});

test("explains that the native host exited before replying", () => {
  assert.equal(
    nativeMessagingError(new Error("Native host has exited.")),
    "Secretariat native host stopped before replying"
  );
});

test("provides a bounded diagnostic for other native-host connection errors", () => {
  assert.equal(
    nativeMessagingError("Error when communicating with the native messaging host."),
    "Secretariat native host is unavailable; check this browser's host registration"
  );
});

test("does not expose unexpected exception text", () => {
  assert.equal(
    nativeMessagingError(new Error("unexpected implementation detail")),
    "Secretariat browser request failed"
  );
});
