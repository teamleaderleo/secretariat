# Secretariat contributor guide

Secretariat is a credential index, reconciliation tool, and bridge between credential stores. The public repository contains reusable code and generated test data only.

## Security boundaries

- Never put passwords, tokens, recovery codes, TOTP seeds, private keys, passkey material, session cookies, browser exports, or raw provider responses in source, fixtures, issues, logs, screenshots, or commit messages.
- Tests use generated sentinels only. A sentinel must not resemble a live credential.
- Never print, serialize, log, publish hashes of, or include a secret value in an exception.
- The Garden is strict and secret-free. Unknown fields fail closed so value-bearing fields cannot silently become versioned metadata.
- Indexed-only copies must refuse value access. Never add a plaintext fallback.
- Reconciliation remains read-only. Propagation, import, rotation, revocation, and deletion need explicit workflows and exact target identity.
- Do not invent encryption, passkey transfer, browser autofill, or cloud-sync protocols. Use mature platform interfaces behind narrow adapters.
- The public repository must stay independent of any real private Garden.

## Development

- Python 3.14 is the canonical runtime for the Python core.
- Keep the core dependency-free until a dependency has a specific reviewed purpose.
- Run `./scripts/check` before pushing.
- Check `git diff --check` and inspect staged files for secret-like material.
- Missing platform tooling should produce a bounded diagnostic and never trigger installation or secret-exposing fallback behavior.
- Secretariat is licensed under Apache-2.0. Optional dependencies retain their own licenses; PyKeePass is GPL-3.0 and must remain an optional integration unless the distribution/licensing consequences are reviewed separately.

## Agent and computer-use handoff

The repository is ready for agent-driven implementation and device testing. Prefer one issue or one independently reviewable capability per branch/PR. Read the relevant issue and current docs before changing code; do not redo a landed capability under a different implementation unless the existing behavior is demonstrably wrong.

For computer-use work, use a temporary Garden and generated credentials only. Do not open, export, photograph, screenshot, inspect, or modify the user's real Chrome, Edge, Apple Passwords, Keychain, KDBX home, or private Garden unless the user explicitly directs that exact action in the active session.

High-value current work:

1. Issue #2: generated macOS -> Google Drive -> Linux KDBX round-trip and conflict/recovery proof. This requires real device interaction and should record reproducible steps without recording secrets.
2. Issue #4: generated Chrome and Edge extension/native-host proof, including wrong-origin, navigation-race, multiple-password-field, browser restart, and host-unavailable cases.
3. Issue #4: design the smallest durable username/account identity addition so several accounts at one site are distinguishable and username + password fill can be supported.
4. Issue #3: Apple AuthenticationServices credential-provider/exchange prototype with generated passwords/passkeys only.
5. Follow-up browser work: noninteractive KDBX unlock and explicit save/update signaling. Never pass the KDBX master password through extension messages, command-line arguments, environment variables, logs, or persisted extension storage.

Stop and leave evidence instead of improvising when a platform requires a private entitlement, signing identity, user approval, biometric prompt, real credential export, or unsupported/private API. A good partial result is a generated-data reproduction, exact error/OS/browser version, screenshots with no private account data, and a narrow next action.
