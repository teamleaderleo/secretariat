import assert from "node:assert/strict";
import test from "node:test";

import { capturePasswordField } from "../password_capture.mjs";

const GENERATED_PASSWORD = "SECRETARIAT-GENERATED-ONLY-CAPTURE-0001";

class FakeInput {
  constructor({ disabled = false, height = 20, readOnly = false, type = "password", visible = true, width = 100, value = "" } = {}) {
    this.disabled = disabled;
    this.height = height;
    this.readOnly = readOnly;
    this.style = {
      display: visible ? "block" : "none",
      visibility: "visible"
    };
    this.type = type;
    this.value = value;
    this.width = width;
  }

  getBoundingClientRect() {
    return { height: this.height, width: this.width };
  }
}

globalThis.HTMLInputElement = FakeInput;
globalThis.getComputedStyle = (element) => element.style;

function installDocument(inputs, activeElement = null) {
  globalThis.document = {
    activeElement,
    querySelectorAll(selector) {
      assert.equal(selector, 'input[type="password"]');
      return inputs;
    }
  };
}

test("captures the only visible generated password field", () => {
  const input = new FakeInput({ value: GENERATED_PASSWORD });
  installDocument([input]);
  assert.deepEqual(capturePasswordField(), { ok: true, password: GENERATED_PASSWORD });
});

test("captures only the focused field when several are visible", () => {
  const first = new FakeInput({ value: "generated-first" });
  const second = new FakeInput({ value: GENERATED_PASSWORD });
  installDocument([first, second], second);
  assert.deepEqual(capturePasswordField(), { ok: true, password: GENERATED_PASSWORD });
});

test("refuses ambiguous multiple password fields", () => {
  const first = new FakeInput({ value: "generated-first" });
  const second = new FakeInput({ value: "generated-second" });
  installDocument([first, second]);
  assert.deepEqual(capturePasswordField(), {
    ok: false,
    error: "focus a password field, or leave exactly one visible password field"
  });
});

test("refuses an empty selected password field", () => {
  const input = new FakeInput({ value: "" });
  installDocument([input]);
  assert.deepEqual(capturePasswordField(), { ok: false, error: "password field is empty" });
});

test("ignores hidden, disabled, read-only, and zero-size password fields", () => {
  const hidden = new FakeInput({ visible: false, value: "generated-hidden" });
  const disabled = new FakeInput({ disabled: true, value: "generated-disabled" });
  const readOnly = new FakeInput({ readOnly: true, value: "generated-read-only" });
  const zeroSize = new FakeInput({ height: 0, value: "generated-zero-size" });
  const visible = new FakeInput({ value: GENERATED_PASSWORD });
  installDocument([hidden, disabled, readOnly, zeroSize, visible]);
  assert.deepEqual(capturePasswordField(), { ok: true, password: GENERATED_PASSWORD });
});
