# Chrome and Edge browser bridge

Secretariat includes an early Manifest V3 browser extension and native messaging host for explicit password filling. The browser never reads Chrome or Edge's built-in password database. It talks only to the Secretariat native host registered for the extension.

## Current capability

The extension can:

- inspect the active HTTP/HTTPS tab after the user opens the Secretariat popup;
- ask the native host which Garden password entries explicitly authorize that page origin through `links.login`;
- show matching titles and optional Garden usernames without sending credential values to the popup;
- distinguish multiple accounts authorized for the same origin; and
- after an explicit click, request one password, fill an unambiguous username field when account metadata exists, and inject the password into the focused password field or the only visible password field on the page.

The first value backend available to the browser host is GNOME Secret Service. KDBX entries are visible as unavailable until a reviewed background unlock mechanism exists. The browser host never tries to open an interactive KDBX password prompt.

## Why there is no permanent content script

The extension uses a popup plus the Manifest V3 service worker. It does not install a persistent content script and does not watch form submissions or keystrokes.

The service worker re-reads the active tab URL for every candidate/fill action. The native host separately checks the requested origin against the credential's declared Garden login URL before a password can be returned.

## Load the extension

The unpacked extension lives in:

```text
browser/extension
```

In Chrome or Edge, enable extension developer mode and load that directory as an unpacked extension. Record the resulting 32-character extension ID.

## Authorize the extension in Secretariat device config

The browser origin must be listed in the per-device Secretariat config:

```json
{
  "browser": {
    "allowed_extension_origins": [
      "chrome-extension://abcdefghijklmnopabcdefghijklmnop/"
    ]
  }
}
```

If the config also contains KDBX settings, keep both top-level objects in the same file.

You can render the browser fragment with:

```text
secretariat browser config-snippet \
  --extension-id abcdefghijklmnopabcdefghijklmnop
```

## Register the native messaging host

Install Secretariat so `secretariat-native-host` is available, then get its absolute path. Render the host manifest with:

```text
secretariat browser manifest \
  --extension-id abcdefghijklmnopabcdefghijklmnop \
  --host-path /absolute/path/to/secretariat-native-host
```

Save that JSON as `com.secretariat.browser.json` in the browser's native messaging host location.

Common user-level locations:

### Google Chrome

macOS:

```text
~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.secretariat.browser.json
```

Linux:

```text
~/.config/google-chrome/NativeMessagingHosts/com.secretariat.browser.json
```

### Microsoft Edge

macOS:

```text
~/Library/Application Support/Microsoft Edge/NativeMessagingHosts/com.secretariat.browser.json
```

Linux:

```text
~/.config/microsoft-edge/NativeMessagingHosts/com.secretariat.browser.json
```

On Windows, register the manifest path under the current-user Chrome or Edge `NativeMessagingHosts\\com.secretariat.browser` registry key. The host manifest's `allowed_origins` entry and Secretariat's device config should name the same extension origin.

If the popup says the native host is not installed for the browser, verify that `com.secretariat.browser.json` exists in that browser's native messaging host location and points to an executable absolute host path. If it says the host does not authorize the extension, compare the unpacked extension ID with both the manifest's `allowed_origins` entry and the Secretariat device config. Reload the unpacked extension after changing its source files.

## Authorize a credential for a site

The browser bridge never guesses from provider names. Set the login URL explicitly in the private Garden:

```text
secretariat garden set-login \
  --alias example-login \
  --url https://example.com/login
```

Only the URL origin is used for matching, so that credential can fill HTTPS pages on `example.com` while remaining unavailable on unrelated origins.

For generated browser proofs only, the `login` link may use HTTP when the host is exactly `localhost`, `127.0.0.1`, or `::1`. This makes it possible to exercise the real browser extension on a controlled loopback page without installing a development certificate. The exception applies only to the login link; `manage`, `revoke`, and `docs` links remain HTTPS-only. Never authorize a real credential for an HTTP loopback page.

Add the account identifier separately:

```text
secretariat garden set-username \
  --alias example-login \
  --username generated-user@example.invalid
```

## Native protocol

The host name is:

```text
com.secretariat.browser
```

Messages use Chrome/Edge native messaging framing: a four-byte native-endian size followed by UTF-8 JSON. Secretariat accepts at most 1 MiB per request even though browsers allow larger extension-to-host messages.

Protocol version 1 currently supports:

- `status` — secret-free capability information;
- `match` — secret-free password titles, aliases, and optional usernames authorized for one exact origin;
- `get` — one explicit alias/origin request returning its optional username metadata and password.

Requests have strict action-specific fields and bounded request IDs. The native host also checks the browser-supplied extension caller origin against device configuration before reading Garden data.

## Real generated-data browser evidence

The bridge has been exercised on macOS 26.6.2 with Chrome 151 and Edge 152 using temporary Gardens, generated credentials, and user-level native-host registrations. The checks covered:

- successful explicit fill on an authorized loopback origin in both browsers;
- rejection of the same page on a different loopback port;
- refusal when two visible password fields were ambiguous, followed by exact fill after one field was focused;
- bounded missing-host diagnostics and recovery after restoring each browser's host manifest;
- full browser restart and native-host reconnection; and
- a delayed-lookup navigation race in which the authorized page moved to another origin before injection and received no credential.

No built-in browser password store, Apple credential store, real Garden, or real credential was used in these proofs.

## Current limitations

- Username selection is deliberately conservative: the extension fills one visible field in the password's form, preferring `autocomplete="username"` and then one email field. It leaves ambiguous username fields untouched rather than guessing.
- GNOME Secret Service is the first fillable backend.
- KDBX browser filling waits for a noninteractive unlock design.
- Save/update propagation from the extension is still disabled.
- Chrome and Edge built-in password stores remain outside this provider path; reconciliation/import handles those existing copies.

These limitations keep the first browser bridge narrow while the save/update semantics and additional backend unlock paths are developed separately.
