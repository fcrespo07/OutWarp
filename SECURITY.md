# Security policy

OutWarp is a tunnel: a flaw in it can expose the traffic or the machines it is
meant to protect. Reports are welcome and taken seriously.

## Reporting a vulnerability

**Do not open a public issue.** Report it privately through GitHub:
**Security → Report a vulnerability** on this repository
(<https://github.com/fcrespo07/OutWarp/security/advisories/new>).

Please include what is affected (client or server, OS, version), how to
reproduce it and what an attacker gains. You will get an answer within a week.
Once a fix is released, the advisory is published with credit to you unless you
prefer otherwise.

## Supported versions

Only the latest release receives security fixes; the in-app updaters make
moving to it a one-click step. Before 1.0.0 there are no maintenance branches.

## What is in scope

- The client and server code in this repository, their installers, the
  enrolment protocol and the `.owcfg` format.
- The update channel: releases are signed with minisign (key `3E1FCD8BF652EC28`,
  `outwarp-release.pub`) and the updaters refuse anything else. See
  `docs/RELEASE_SIGNING.md`.

Vulnerabilities in wstunnel or WireGuard themselves belong upstream; if OutWarp
uses them in a way that makes one exploitable, that part is in scope here.
