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
