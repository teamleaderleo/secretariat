import assert from "node:assert/strict";
import test from "node:test";

import { sendNativeRequest } from "../native_request.mjs";

test("resolves a native-host response", async () => {
  const response = { ok: true };
  const runtime = {
    lastError: null,
    sendNativeMessage(hostName, request, callback) {
      assert.equal(hostName, "com.secretariat.browser");
      assert.deepEqual(request, { action: "status" });
      callback(response);
    }
  };

  assert.equal(
    await sendNativeRequest(runtime, "com.secretariat.browser", { action: "status" }),
    response
  );
});

test("rejects with runtime.lastError while it is available in the callback", async () => {
  const runtime = {
    lastError: null,
    sendNativeMessage(_hostName, _request, callback) {
      this.lastError = { message: "Specified native messaging host not found." };
      callback(undefined);
      this.lastError = null;
    }
  };

  await assert.rejects(
    sendNativeRequest(runtime, "com.secretariat.browser", { action: "status" }),
    { message: "Specified native messaging host not found." }
  );
});

test("rejects a missing response without exposing request contents", async () => {
  const runtime = {
    lastError: null,
    sendNativeMessage(_hostName, _request, callback) {
      callback(undefined);
    }
  };

  await assert.rejects(
    sendNativeRequest(runtime, "com.secretariat.browser", { action: "get" }),
    { message: "Native messaging host returned no response." }
  );
});
