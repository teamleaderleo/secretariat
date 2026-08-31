import assert from "node:assert/strict";
import test from "node:test";

import { fillPasswordField } from "../password_fill.mjs";

const GENERATED_PASSWORD = "SECRETARIAT-GENERATED-ONLY-UNIT-0001";

class FakeInput {
  constructor({ disabled = false, height = 20, readOnly = false, type = "password", visible = true, width = 100 } = {}) {
    this.disabled = disabled;
    this.height = height;
    this.readOnly = readOnly;
    this.style = {
      display: visible ? "block" : "none",
      visibility: "visible"
    };
    this.type = type;
    this.width = width;
    this.events = [];
    this._value = "";
  }

  get value() {
    return this._value;
  }

  set value(value) {
    this._value = value;
  }

  dispatchEvent(event) {
    this.events.push({ bubbles: event.bubbles, type: event.type });
    return true;
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

test("fills the only visible password field and dispatches framework-compatible events", () => {
  const input = new FakeInput();
  installDocument([input]);

  assert.deepEqual(fillPasswordField(GENERATED_PASSWORD), { ok: true });
  assert.equal(input.value, GENERATED_PASSWORD);
  assert.deepEqual(input.events, [
    { bubbles: true, type: "input" },
    { bubbles: true, type: "change" }
  ]);
});

test("refuses an ambiguous page with multiple visible password fields", () => {
  const first = new FakeInput();
  const second = new FakeInput();
  installDocument([first, second]);

  assert.deepEqual(fillPasswordField(GENERATED_PASSWORD), {
    error: "focus a password field, or leave exactly one visible password field",
    ok: false
  });
  assert.equal(first.value, "");
  assert.equal(second.value, "");
});

test("fills only the focused field when several password fields are visible", () => {
  const first = new FakeInput();
  const second = new FakeInput();
  installDocument([first, second], second);

  assert.deepEqual(fillPasswordField(GENERATED_PASSWORD), { ok: true });
  assert.equal(first.value, "");
  assert.equal(second.value, GENERATED_PASSWORD);
});

test("ignores hidden, disabled, read-only, and zero-size password fields", () => {
  const hidden = new FakeInput({ visible: false });
  const disabled = new FakeInput({ disabled: true });
  const readOnly = new FakeInput({ readOnly: true });
  const zeroSize = new FakeInput({ height: 0 });
  const visible = new FakeInput();
  installDocument([hidden, disabled, readOnly, zeroSize, visible]);

  assert.deepEqual(fillPasswordField(GENERATED_PASSWORD), { ok: true });
  assert.equal(visible.value, GENERATED_PASSWORD);
  for (const excluded of [hidden, disabled, readOnly, zeroSize]) {
    assert.equal(excluded.value, "");
  }
});
