<!--
SPDX-FileCopyrightText: 2026 MASH project contributors

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Gluetun Ansible role

This Ansible role installs [Gluetun](https://github.com/passteque/gluetun)
as a Docker container wrapped in a systemd service.

The role is deliberately scoped to a fail-closed, one-owner/one-consumer
network-namespace design. A protected container can join Gluetun with
`--network=container:<resolved-full-gluetun-container-ID>`. It then has no
independent Docker network or published ports and cannot fall back to the
host's Internet route when the VPN tunnel fails.

Here, fail-closed means Internet isolation, not necessarily process
termination. During an ordinary in-process tunnel outage, the protected
service may remain running and an explicitly configured local diagnostic path
may remain reachable.

The role implicitly depends on:

- [`com.devture.ansible.role.playbook_help`](https://github.com/devture/com.devture.ansible.role.playbook_help)
- [`com.devture.ansible.role.systemd_docker_base`](https://github.com/devture/com.devture.ansible.role.systemd_docker_base)

See [`defaults/main.yml`](defaults/main.yml) for the supported options and
[`docs/configuring-gluetun.md`](docs/configuring-gluetun.md) for the security
and integration contract.

## Security boundary

The role:

1. pins a Gluetun release by tag and digest and attests the local image content;
2. creates one dedicated IPv4-only bridge;
3. keeps Gluetun's firewall, encrypted DNS and VPN auto-healing enabled;
4. exposes no host ports, proxies, port forwarding or arbitrary Docker
   arguments;
5. stores VPN credentials and the read-only diagnostic API-key policy as
   mode-`0600` files mounted read-only at `/run/secrets`, with no key in the
   environment;
6. isolates stale or standalone protected consumers before owner mutations;
7. requires fixed identity and versioned fail-closed contract labels, then
   attests the complete owner image, effective image-plus-role environment,
   network and runtime contract before preserving it;
8. mutates captured full container IDs and refuses unverified replacements;
9. installs an inert persistent systemd quiesce before owner replacement or
   removal, adopts it on recovery from an interrupted run, and releases it
   only after attesting the complete effective final or absent unit state;
10. rejects unknown containers sharing the owner's actual network namespace;
11. validates consumer unit ownership, dependency and runtime exact-ID
    contract markers;
12. forces owner and protected-service DNS through Gluetun loopback;
13. waits for Docker health before the systemd start job succeeds;
14. cooperates with consumer-side `BindsTo=` stop coupling;
15. stops and verifies protected consumers before removing the namespace owner;
16. never force-disconnects another container when removing its bridge.

Gluetun must run its entrypoint as root with network-administration
capabilities and access to `/dev/net/tun`. This role grants the normal Docker
default capability set plus `NET_ADMIN`, explicitly rather than using
`--privileged`.

The guarantee covers managed lifecycle operations and ordinary VPN tunnel
loss. It assumes the protected process is not deliberately trying to bypass
the tunnel: every process in the shared namespace can address the narrow
provider bootstrap/control-plane tuple that Gluetun must allow to establish and
maintain the VPN. Direct out-of-band commands such as
`docker restart gluetun` also bypass systemd stop coupling and are outside the
guarantee. See the configuration guide for the complete threat boundary.

## Development

You can optionally install a Git pre-commit hook with:

```sh
just prek-install-git-pre-commit-hook
```

Run the non-runtime rendering and policy fixtures with:

```sh
just test-static
```
