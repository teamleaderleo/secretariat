export function fillLoginFields(username, password) {
  const inputs = [...document.querySelectorAll("input")];
  const isVisibleWritableInput = (element) => {
    if (!(element instanceof HTMLInputElement) || element.disabled || element.readOnly) return false;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const visiblePasswordInputs = inputs.filter(
    (element) => element.type === "password" && isVisibleWritableInput(element)
  );

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

  let usernameTarget = null;
  if (typeof username === "string" && username.length > 0) {
    let candidates = inputs.filter((element) => {
      const type = String(element.type || "text").toLowerCase();
      return ["email", "tel", "text"].includes(type) && isVisibleWritableInput(element);
    });
    if (target.form) {
      candidates = candidates.filter((element) => element.form === target.form);
    }
    const passwordIndex = inputs.indexOf(target);
    const preceding = candidates.filter((element) => inputs.indexOf(element) < passwordIndex);
    candidates = preceding.length > 0 ? preceding : [];

    const autocompleteMatches = candidates.filter((element) =>
      String(element.autocomplete || "")
        .toLowerCase()
        .split(/\s+/)
        .includes("username")
    );
    if (autocompleteMatches.length === 1) {
      usernameTarget = autocompleteMatches[0];
    } else if (autocompleteMatches.length === 0) {
      const emailMatches = candidates.filter((element) => element.type === "email");
      if (emailMatches.length === 1) {
        usernameTarget = emailMatches[0];
      } else if (emailMatches.length === 0 && candidates.length === 1) {
        usernameTarget = candidates[0];
      }
    }
  }

  if (usernameTarget) {
    descriptor.set.call(usernameTarget, username);
    usernameTarget.dispatchEvent(new Event("input", { bubbles: true }));
    usernameTarget.dispatchEvent(new Event("change", { bubbles: true }));
  }
  descriptor.set.call(target, password);
  target.dispatchEvent(new Event("input", { bubbles: true }));
  target.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true, username_filled: usernameTarget !== null };
}

export function fillPasswordField(password) {
  const result = fillLoginFields(null, password);
  return result.ok ? { ok: true } : result;
}
