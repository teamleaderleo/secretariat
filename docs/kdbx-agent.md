# KDBX unlock agent

Secretariat can keep an explicitly unlocked KDBX home available to short-lived browser/native-provider processes without passing the KDBX master password to those processes.

The first implementation is intentionally a foreground user process. It does not daemonize, auto-start, or auto-unlock.

## Start, inspect, and lock

Install the optional KDBX integration and ensure the device config points at the encrypted home:

```text
python -m pip install -e '.[kdbx]'
secretariat-kdbx-agent serve
```

`serve` prompts for the KDBX master password in the agent process, opens the configured database, binds a user-only Unix-domain socket, and stays in the foreground. The default session expires after 15 minutes without a credential read/write and after two hours regardless of activity.

Use another terminal to inspect or lock it:

```text
secretariat-kdbx-agent status
secretariat-kdbx-agent lock
```

Custom time bounds are explicit:

```text
secretariat-kdbx-agent serve --idle-seconds 600 --ttl-seconds 3600
```

The first implementation supports macOS and Linux, where Python exposes `AF_UNIX` Unix-domain sockets. Windows browser use continues to treat KDBX as locked until a reviewed Windows IPC design exists.

## Runtime locations

macOS:

```text
~/Library/Caches/Secretariat/run/kdbx-agent.sock
```

Linux uses `$XDG_RUNTIME_DIR/secretariat/kdbx-agent.sock` when `XDG_RUNTIME_DIR` exists, otherwise:

```text
~/.cache/secretariat/run/kdbx-agent.sock
```

The immediate runtime directory is required to be owned by the current user and is set to mode `0700`. The socket is mode `0600`. Secretariat refuses to replace a non-socket object at the socket path and only removes a stale socket owned by the current user.

## Protocol boundary

The agent uses a small length-prefixed JSON protocol over the Unix socket. Protocol version 1 supports:

- `status` — secret-free remaining idle/absolute lifetime;
- `get` — exact canonical KDBX entry UUID -> password value;
- `put` — exact canonical KDBX entry UUID + password value -> update;
- `lock` — stop the agent and remove the socket.

Messages are bounded to 1 MiB. Credential values are bounded to 65,536 characters. Put-request values are excluded from Python dataclass `repr` output. The protocol has no action for listing KDBX titles, usernames, groups, or arbitrary database contents.

The browser native host probes the agent. While it is reachable, enrolled KDBX homes become fillable and explicitly updatable through their exact Garden UUID. When the agent is absent/expired/locked, the browser shows the KDBX home as locked.

## Revision binding

Unlock binds the in-memory database object to the encrypted KDBX file fingerprint that existed at unlock time.

Before and after reads, and before writes, the agent checks that encrypted file revision. If Google Drive, another device, KeePassXC, or another process replaces/changes the KDBX file, the session invalidates and refuses further value access. The user must review the competing revision and explicitly unlock again.

After an agent-owned successful write, the session records the new encrypted-file fingerprint and continues against that revision. Existing KDBX entry-history and atomic-save behavior is preserved.

## Threat model

This boundary is meant to accomplish two things:

1. Browser extension/service-worker/native-host processes never receive the KDBX master password.
2. Other OS users cannot simply connect to the agent socket through a world-readable endpoint.

It does **not** claim to defend against arbitrary malicious code already executing as the same OS user. Such a process may have other ways to inspect the user's processes, files, GUI session, or IPC. The Unix socket is an OS-user/session boundary, not a sandbox against a compromised account.

The decrypted database and credential values necessarily exist in agent process memory while the session is unlocked. Python does not provide a reliable guarantee that immutable password strings can be zeroized from memory, so Secretariat does not make such a claim. Expiry/lock drops the live database reference and removes the listening socket.

There is deliberately no extra home-grown encryption or bearer-token protocol layered over the Unix socket. If stronger same-user isolation becomes a requirement, use an OS facility with a real authenticated process boundary rather than inventing application cryptography.

## Still separate

- OS login/startup integration and background service packaging;
- macOS Keychain or Linux Secret Service assistance for starting/unlocking the agent;
- Windows IPC;
- real-device browser proof of KDBX fill/update;
- a richer UI for lock state and session lifetime.
