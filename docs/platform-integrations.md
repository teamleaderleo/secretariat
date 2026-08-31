# Platform integrations

Secretariat prefers supported platform interfaces over scraping password-manager internals.

## Apple

The intended Apple path combines three AuthenticationServices capabilities:

- credential exchange for password/passkey convergence between participating managers;
- credential-provider AutoFill for credentials managed through Secretariat;
- system-delivered save/update requests for Secretariat-managed passwords.

These capabilities do not imply a general background feed of every pre-existing Apple Passwords record.

## Chrome and Edge

Built-in desktop password stores currently enter reconciliation through deliberate exports. Secretariat does not read Chromium `Login Data` databases or use browser-private password APIs from unsupported contexts.

The provider path is a Manifest V3 extension using native messaging:

`page/content context -> extension service worker -> native messaging -> Secretariat broker -> reviewed credential backend`

Content-script input is treated as untrusted and validated again before privileged operations. Reusable credential values do not belong in persistent extension storage.

## Android / Google Password Manager

Password/passkey exchange APIs are the preferred convergence mechanism when available to participating credential managers. Desktop browser snapshot/import workflows remain separate from that provider-exchange path.

## Linux

GNOME Secret Service is the first implemented value adapter. A portable KDBX home is intended to reduce the need to duplicate every credential into the machine keyring.

## KDBX

KDBX is intended as the first portable encrypted home. Exact entry identity must be stable and unambiguous; title/path matching is insufficient for authoritative operations.
