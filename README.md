# Secretariat

Secretariat is a personal credential index, reconciliation tool, and bridge between password stores.

Passwords, passkeys, tokens, browser logins, native keychains, and encrypted vault entries can all be represented as copies of one logical credential. Secretariat keeps the inventory and relationships clear, helps compare duplicate or conflicting copies, and gives each enrolled credential an explicit home.

The public repository contains software, generated examples, tests, and documentation only. Real account metadata belongs in a separate private Garden. Credential values belong in a reviewed secret backend such as an encrypted KDBX home or a native credential store.

## What works today

- Garden schema v3: one logical credential, multiple copies, one explicit home;
- `find`, `show`, `list`, expiry/rotation views, and diagnostics;
- read-only reconciliation of Chrome, Edge, and Apple Passwords CSV snapshots;
- duplicate, conflict, multi-account, notes-presence, OTP-presence, and same-source-conflict reporting without printing credential values;
- a private standalone HTML reconciliation review that can export a strict secret-free Garden enrollment plan;
- atomic `garden apply-plan` enrollment of reviewed reconciliation decisions without overwriting existing aliases;
- explicit one-account migration from a reviewed Chrome/Edge/Apple snapshot home into a new exact-UUID portable KDBX home;
- GNOME Secret Service value access for explicitly configured home copies;
- optional exact-UUID KDBX home read/write through PyKeePass, with entry history and encrypted-file divergence checks;
- explicit KDBX home creation, UUID-backed entry enrollment, value-silent verification, and a foreground macOS/Linux unlock agent for browser access;
- atomic secret-free Garden metadata editing;
- a generated-data Chrome/Edge Manifest V3 + native-messaging bridge for exact-origin username/password fill and explicit password updates;
- real generated-data Chrome/Edge proof for fill, origin/race boundaries, missing-host recovery, and browser restart;
- a generated-data macOS AuthenticationServices capability probe for password/passkey identities and credential exchange;
- repository scanning for several common secret formats;
- indexed copy types for Apple Passwords, Chrome, Edge, macOS Keychain, SSH agent, KDBX, and external providers.

Apple credential-provider packaging, cross-device Linux proof, real-device proof of KDBX browser access/update, and OS service packaging for the unlock agent remain under development.

## Run from a checkout

Secretariat currently targets Python 3.14 and keeps the Python core dependency-free.

```text
./scripts/check
./scripts/secretariat --garden garden.example.json list
./scripts/secretariat --garden garden.example.json find browser
./scripts/secretariat --garden garden.example.json show example-browser-login
```

An installed command is also exposed through `pyproject.toml`:

```text
secretariat --garden /path/to/garden.json list
```

Set `SECRETARIAT_GARDEN` to keep the private Garden outside the public checkout:

```text
export SECRETARIAT_GARDEN="$HOME/path/to/secretariat-garden/garden.json"
secretariat list
```

An explicit `--garden` path takes precedence.

## Reconcile existing password stores

Create deliberate temporary exports from the stores you want to compare, keep those plaintext files outside Git, then run:

```text
secretariat reconcile \
  --snapshot chrome_passwords=/private/path/chrome.csv \
  --snapshot edge_passwords=/private/path/edge.csv \
  --snapshot apple_passwords=/private/path/apple.csv \
  --html /private/path/secretariat-review.html
```

The reconciliation engine compares passwords only in process memory. Reports contain account metadata such as sites, usernames, source names, and copy counts. They contain no password values, password-derived fingerprints, note contents, or OTP secrets.

The HTML review can turn explicit choices into `secretariat-garden-plan.json`. Select the accounts you want to enroll, edit their aliases, choose a home copy for multi-source credentials, then apply the downloaded plan to the private Garden:

```text
secretariat \
  --garden /private/path/garden.json \
  garden apply-plan \
  --plan /private/path/secretariat-garden-plan.json
```

Plan application only adds new logical credentials. It validates the entire plan first, refuses existing aliases or incomplete homes, and atomically replaces the Garden only after the complete proposed Garden passes schema validation.

A reviewed entry whose current home is still an indexed Chrome/Edge/Apple snapshot copy can then be promoted one account at a time into KDBX without putting its password into the review plan:

```text
secretariat \
  --garden /private/path/garden.json \
  migrate to-kdbx example-login \
  --snapshot apple_passwords=/private/path/apple.csv
```

The migration requires that source to be the Garden entry's current home and resolves it by exact login origin + username. It creates a new encrypted KDBX entry, attaches the returned UUID as copy `portable`, and makes that copy home. The original snapshot copy remains recorded as a replica. See [`docs/reconciliation.md`](docs/reconciliation.md) for the two-store race/recovery behavior.

## Garden and value storage

A Garden is secret-free private metadata. A logical credential can have several copies:

```json
{
  "alias": "example-login",
  "title": "Example login",
  "username": "generated-user@example.invalid",
  "kind": "password",
  "provider": "example",
  "copies": [
    {
      "id": "portable",
      "type": "kdbx",
      "reference": "00112233445566778899aabbccddeeff"
    },
    {
      "id": "apple",
      "type": "apple_passwords",
      "reference": "example.invalid"
    }
  ],
  "home": "portable"
}
```

The Garden stores references and intent. It never stores the password itself.

### Portable KDBX home

Install the optional adapter:

```text
python -m pip install -e '.[kdbx]'
```

Then configure the encrypted database path per device. The master password stays out of the config and is prompted when the CLI opens the home. See [`docs/kdbx-home.md`](docs/kdbx-home.md) for the exact config paths, UUID contract, write behavior, and cloud-transport boundary.

For browser access on macOS/Linux, `secretariat-kdbx-agent serve` explicitly unlocks the configured KDBX home in one foreground process and exposes only exact-UUID get/put operations through a user-only Unix socket. See [`docs/kdbx-agent.md`](docs/kdbx-agent.md).

Native password managers remain useful interfaces and replicas around the same logical credential.

### Chrome and Edge

The browser bridge lives under `browser/extension` and communicates with `secretariat-native-host`. It authorizes fills and explicit password updates against an explicit Garden login URL and re-checks the active tab origin before value transfer. It does not watch forms or read Chrome/Edge's built-in password databases. See [`docs/browser-bridge.md`](docs/browser-bridge.md) for generated-data setup and current limitations.

## Repository split

A practical deployment uses three separate locations:

- **this public repository** — reusable code and generated examples;
- **a private Garden repository** — real account/source metadata and reconciliation decisions;
- **an encrypted KDBX file outside Git** — actual portable credential values.

Device-specific unlock material, browser host registration, cloud credentials, and absolute private paths stay outside both repositories.

## Safety rules

- Never commit passwords, tokens, recovery codes, TOTP seeds, private keys, passkey material, cookies, browser exports, or KDBX databases.
- Treat CSV exports from password managers as plaintext secret material.
- Indexed copies stay unable to retrieve values until an exact reviewed migration/provider path is used.
- Multiple copies require an explicit home before Secretariat performs value operations.
- Reconciliation reads snapshots only; reviewed plan application mutates Garden metadata only.
- Snapshot-to-KDBX migration handles one explicit account/source at a time and never deletes the source copy.
- External-store propagation, source-side deletion, and replica retirement remain separate explicit workflows.

See `SECURITY.md` and the docs directory for the detailed boundaries.

## License

Secretariat is licensed under the Apache License 2.0. See `LICENSE` and `NOTICE`.

The optional `kdbx` extra uses PyKeePass, which is separately licensed under GPL-3.0. PyKeePass retains its own license terms; redistributors should review the obligations that apply to the form in which they distribute or bundle optional dependencies.
