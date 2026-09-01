# Portable KDBX home

Secretariat can use a KDBX entry as the authoritative value for an enrolled credential. The Garden stores only the entry UUID. Each device separately configures where the encrypted database file is available.

## Install the optional adapter

```text
python -m pip install -e '.[kdbx]'
```

The `kdbx` extra currently uses PyKeePass 4.2 or newer for KDBX3/KDBX4 read and write access. PyKeePass is GPL-3.0 licensed and remains an optional integration.

## Device configuration

macOS default config path:

```text
~/Library/Application Support/Secretariat/config.json
```

Linux default config path:

```text
${XDG_CONFIG_HOME:-~/.config}/secretariat/config.json
```

Example:

```json
{
  "kdbx": {
    "path": "/path/to/Google Drive/Secretariat/secretariat.kdbx"
  }
}
```

`SECRETARIAT_CONFIG` can point at a different config file. `SECRETARIAT_KDBX_PATH` can override the KDBX path for a process. The database master password is absent from both configuration mechanisms; interactive CLI operations prompt for it when the KDBX home is opened.

## Inspect home state

```text
secretariat home status
```

The status command never opens an encrypted entry or returns a credential value. It combines dependency/path/file readiness with the short-lived KDBX unlock-agent state.

Common `state` values:

- `dependency_missing` — install the optional KDBX extra;
- `config_missing` — no KDBX path is configured on this device;
- `file_missing` — the configured encrypted file is not currently present;
- `path_unsafe` — the configured database path is a symlink, which the KDBX backend refuses;
- `available_locked` — the encrypted file is available for interactive CLI unlock, but no usable browser unlock-agent session is running;
- `available_unlocked` — the agent is running and its health check confirms the encrypted file still matches the revision opened at unlock;
- `changed_since_unlock` — the status probe discovered that the encrypted KDBX file changed after the agent opened it, so the old session is being invalidated;
- `agent_unsafe` or `agent_unavailable` — the configured file exists, but the agent endpoint cannot be trusted/reached.

When unlocked, status also reports the remaining idle and absolute session lifetime. `--json` returns the same metadata in machine-readable form.

The installed `secretariat-kdbx-agent status` command performs the same revision-aware health probe. A Drive/KeePassXC replacement discovered by that probe invalidates the running session rather than continuing to advertise it as unlocked.

## Create the encrypted home

Once the KDBX path points into an existing synced folder, create the database explicitly:

```text
secretariat home init
```

The command prompts twice for a new KDBX master password, refuses an existing target, writes an encrypted mode-0600 temporary database in the same directory, and atomically installs it. The master password is neither printed nor written to Secretariat configuration.

## Add an entry

Add one password-like value to the encrypted home:

```text
secretariat home add \
  --title "Example login" \
  --username "user@example.com" \
  --url "https://example.com/login"
```

The command prompts twice for the credential value, then prompts for the KDBX master password. Its only credential-specific output is the stable entry UUID:

```text
kdbx_uuid: 00112233445566778899aabbccddeeff
```

That UUID can be placed into the private Garden as a KDBX copy reference. `home add` deliberately does not edit the Garden; attaching a new entry to a logical credential remains an explicit separate action.

## Garden copy

A KDBX copy uses the entry UUID as exactly 32 lowercase hexadecimal characters:

```json
{
  "id": "portable",
  "type": "kdbx",
  "reference": "00112233445566778899aabbccddeeff"
}
```

Titles and group paths are mutable and may be ambiguous, so Secretariat rejects them as KDBX identity. The current KeePassXC command-line client still lacks an exact UUID selection command; the adapter therefore uses PyKeePass's UUID lookup instead of title/path matching.

Reviewed Chrome/Edge/Apple reconciliation entries can also be promoted one account at a time with `secretariat migrate to-kdbx ...`; see `docs/reconciliation.md`.

## Reads

`copy` and `run` can read a KDBX home once the optional dependency and device path are available. Secretariat resolves exactly one entry by UUID and reads its protected Password field.

On macOS, prove an enrolled entry can be unlocked and resolved without placing its value on a clipboard or exposing it to a child process:

```text
secretariat --garden /path/to/generated-garden.json home verify example-login
```

`home verify` prompts for the KDBX master password, resolves the Garden's exact home-copy UUID, requires a non-empty protected Password field, and discards the value. Its output contains only the alias and home-copy ID.

Passkeys are excluded from this generic value path. They remain in platform credential-provider/exchange APIs.

## Browser unlock agent

On macOS/Linux, `secretariat-kdbx-agent serve` keeps one explicitly unlocked KDBX object in a foreground process and exposes only exact-UUID get/put operations over a user-only Unix socket. Browser native-host processes never receive the KDBX master password. See `docs/kdbx-agent.md` for the threat model, expiry behavior, and IPC boundary.

## Writes and conflicts

Before changing an entry, Secretariat records a fingerprint of the encrypted KDBX file, saves the previous entry version into KDBX history, updates the password field, and writes a new encrypted database to a mode-0600 temporary file in the same directory.

Immediately before replacing the home file, Secretariat verifies that the original encrypted file is unchanged. If another process or cloud transport changed it, the write stops with a divergence error. The temporary file is discarded and the competing revision stays intact for review.

The unlock agent is revision-bound too. Its value reads/writes and revision-aware status probe stop using the session after the encrypted file changes underneath it.

A successful write uses an atomic same-directory replacement where the platform supports it. Cloud version history remains valuable recovery evidence.

## Transport boundary

Secretariat has no Google Drive credentials or cloud API code in the KDBX adapter. A transport such as Google Drive, rclone, Syncthing, Dropbox, or Nextcloud only moves the already-encrypted KDBX file between devices.

For a Mac/Linux setup using Google Drive:

```text
Mac provider/browser -> Secretariat -> KDBX -> Google Drive -> Linux -> Secretariat
```

Google Drive for desktop can supply the Mac path. Linux can use a separately configured Drive client such as rclone. Those transport credentials and paths stay in device configuration outside the Garden.

In Finder list view, wait for Google Drive for desktop's upload progress indicator to disappear without an error. A streamed file may then be labelled `Online only`. Treat that as Mac-side transport evidence, not as the cross-device proof: the Linux side must still retrieve the same encrypted file and run `home verify` against the enrolled UUID.

## Current scope

Secretariat now has explicit home creation, exact-UUID entry creation/read/write, reviewed Garden enrollment, snapshot-to-KDBX promotion, value-silent verification, and a foreground macOS/Linux browser unlock agent. Remaining work includes cross-device Linux proof, OS service/startup packaging for the agent, Windows agent IPC, optional OS credential assistance for unlock, and richer conflict/recovery UI.
