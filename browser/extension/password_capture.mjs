export function capturePasswordField() {
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

  const password = target.value;
  if (typeof password !== "string" || password.length === 0) {
    return { ok: false, error: "password field is empty" };
  }
  return { ok: true, password };
}
