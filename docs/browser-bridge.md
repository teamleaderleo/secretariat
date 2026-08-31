# Chrome and Edge browser bridge

Secretariat includes a Manifest V3 browser extension and native messaging host for explicit password use and updates. The browser never reads Chrome or Edge's built-in password database. It talks only to the Secretariat native host registered for the extension.

## Current capability

The extension can:

- inspect the active HTTP/HTTPS tab after the user opens the Secretariat popup;
- ask the native host which Garden password entries explicitly authorize that page origin through `links.login`;
- show matching titles and optional Garden usernames without sending credential values to the popup;
- distinguish multiple accounts authorized for the same origin;
- after an explicit click, request one password, fill an unambiguous username field when account metadata exists, and inject the password into the focused password field or the only visible password field on the page; and
- after a separate explicit confirmation, read the focused password field (or the only visible password field) and replace the enrolled password in a backend the browser host can already open safely.

GNOME Secret Service is directly available to the browser host when its helper is present. On macOS/Linux, KDBX homes become browser-fillable/updatable only while the explicit Secretariat KDBX unlock agent is running. The browser host never prompts for or receives the KDBX master password. See [`kdbx-agent.md`](kdbx-agent.md).

## Why there is no permanent content script

The extension uses a popup plus the Manifest V3 service worker. It does not install a persistent content script and does not watch form submissions or keystrokes.

The service worker re-reads the active tab URL for every candidate/fill/update action. The native host separately checks the requested origin against the credential's declared Garden login URL before a password can be returned or replaced.

Updating is deliberately user-driven. Secretariat does not observe password fields in the background, does not intercept form submissions, and does not automatically copy changes out of Chrome or Edge's built-in password manager.

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

Only the URL origin is used for matching, so that credential can fill or update from HTTPS pages on `example.com` while remaining unavailable on unrelated origins.

For generated browser proofs only, the `login` link may use HTTP when the host is exactly `localhost`, `127.0.0.1`, or `::1`. This makes it possible to exercise the real browser extension on a controlled loopback page without installing a development certificate. The exception applies only to the login link; `manage`, `revoke`, and `docs` links remain HTTPS-only. Never authorize a real credential for an HTTP loopback page.

Add the account identifier separately:

```text
secretariat garden set-username \
  --alias example-login \
  --username generated-user@example.invalid
```

## Use a KDBX home from the browser

On macOS/Linux, start the foreground unlock agent from an installed environment with the KDBX extra:

```text
secretariat-kdbx-agent serve
```

After the master-password prompt succeeds, the agent owns the open KDBX session. Browser native-host processes connect to its user-only Unix socket and request only exact Garden KDBX UUIDs. When the agent expires or is explicitly locked, KDBX cards return to **KDBX locked — start unlock agent** and their Fill/Update buttons are disabled.

The browser native host does not need to receive the master password and does not attempt an interactive unlock itself.

## Explicit password update

For a fillable/updatable credential, the popup exposes **Update saved password** separately from **Fill**. The update path:

1. asks for confirmation before overwriting the enrolled value;
2. reads only the focused visible writable password field, or exactly one visible writable password field when there is no focused password field;
3. refuses empty or ambiguous page password fields;
4. rechecks the active tab origin after capture and before sending the value to the native host;
5. sends one bounded `update` message containing the alias, exact origin, and password;
6. has the native host independently authorize that alias/origin and store it only through an available backend; and
7. returns only success/failure to the popup.

The captured password is never placed in extension storage, ordinary output, logs, Garden metadata, or an error message. For KDBX, the value passes from the browser native host to the explicitly unlocked agent over the user-only Unix socket; the master password never travels that path.

## Native protocol

The host name is:

```text
com.secretariat.browser
```

Messages use Chrome/Edge native messaging framing: a four-byte native-endian size followed by UTF-8 JSON. Secretariat accepts at most 1 MiB per request even though browsers allow larger extension-to-host messages. Browser password updates apply a tighter 16,384-character value bound.

Protocol version 1 currently supports:

- `status` — secret-free capability information;
- `match` — secret-free password titles, aliases, optional usernames, and capability flags authorized for one exact origin;
- `get` — one explicit alias/origin request returning its optional username metadata and password; and
- `update` — one explicit alias/origin/password request that replaces the enrolled backend value and returns no credential value.

Requests have strict action-specific fields and bounded request IDs. The parsed update request marks the password field non-representable so normal request debugging cannot stringify it. The native host also checks the browser-supplied extension caller origin against device configuration before reading Garden data or changing a backend.

## Real generated-data browser evidence

The fill bridge has been exercised on macOS 26.6.2 with Chrome 151 and Edge 152 using temporary Gardens, generated credentials, and user-level native-host registrations. The checks covered successful explicit fill, exact origin/port rejection, ambiguous-field refusal, missing-host recovery, browser restart/reconnection, and a navigation race where the destination received no credential.

The explicit browser update path and the new KDBX unlock-agent browser path have generated repository coverage; corresponding real-device proofs remain follow-up validation rather than a prerequisite for the code boundary.

## Current limitations

- Username selection is deliberately conservative and leaves ambiguous username fields untouched rather than guessing.
- KDBX browser access currently requires a foreground unlock-agent process on macOS/Linux; there is no startup/service integration yet.
- Windows KDBX browser IPC is not implemented.
- Browser updates are explicit; there is no automatic save event or background form monitoring.
- Chrome and Edge built-in password stores remain outside this provider path; reconciliation/import handles those existing copies.
