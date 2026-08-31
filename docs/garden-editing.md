# Editing the private Garden

Secretariat can make explicit metadata-only edits to a Garden file. These commands never read or write credential values.

Point Secretariat at the private Garden with `--garden` or `SECRETARIAT_GARDEN`.

## Add a logical credential

After `secretariat home add` returns a KDBX UUID, create the logical credential:

```text
secretariat garden add \
  --alias github-personal \
  --title "GitHub personal" \
  --kind password \
  --provider github \
  --copy-id portable \
  --copy-type kdbx \
  --reference 00112233445566778899aabbccddeeff
```

The first copy becomes the explicit home.

## Set the login URL

A credential can declare the credential-free HTTPS login URL used by browser integrations:

```text
secretariat garden set-login \
  --alias github-personal \
  --url https://github.com/login
```

The browser bridge compares the page origin with this login URL before it will offer or retrieve the credential. It does not infer authorization from the provider name or source reference.

## Attach another copy

Record an Apple, Chrome, Edge, native-keychain, or other existing replica:

```text
secretariat garden attach \
  --alias github-personal \
  --copy-id apple \
  --copy-type apple_passwords \
  --reference "github.com:user@example.com"
```

The existing home stays authoritative. Add `--home` when the newly attached copy should become authoritative.

## Choose a home

```text
secretariat garden set-home \
  --alias github-personal \
  --copy-id portable
```

A home always names one of the copies on the logical credential.

## Detach a replica

```text
secretariat garden detach \
  --alias github-personal \
  --copy-id edge
```

Detaching the current home requires an explicit replacement in the same action:

```text
secretariat garden detach \
  --alias github-personal \
  --copy-id edge \
  --new-home portable
```

Secretariat refuses to detach the only copy.

## File-safety behavior

Before every edit Secretariat validates the current Garden and records a fingerprint of the file. The proposed document is validated again through the Garden schema before it is written. A changed Garden file causes the edit to stop with a divergence error.

Successful edits are written to a mode-0600 temporary file in the same directory and then atomically replace the prior Garden file. This protects against half-written JSON and makes competing Git/editor changes visible instead of silently overwriting them.

The Garden contains private account metadata even though it contains no password/token/passkey values. Keep the real Garden in a private repository and keep browser exports, KDBX files, reconciliation reports, and machine configuration outside it.
