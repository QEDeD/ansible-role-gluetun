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

The role implicitly depends on:

- [`com.devture.ansible.role.playbook_help`](https://github.com/devture/com.devture.ansible.role.playbook_help)
- [`com.devture.ansible.role.systemd_docker_base`](https://github.com/devture/com.devture.ansible.role.systemd_docker_base)

See [`defaults/main.yml`](defaults/main.yml) for the supported options and
[`docs/configuring-gluetun.md`](docs/configuring-gluetun.md) for the security
and integration contract.

## Security boundary

The role:

1. pins a stable Gluetun release;
2. creates one dedicated IPv4-only bridge;
3. keeps Gluetun's firewall, encrypted DNS and VPN auto-healing enabled;
4. exposes no host ports, proxies, port forwarding or arbitrary Docker
   arguments;
5. stores VPN credentials as mode-`0600` files mounted read-only at
   `/run/secrets`;
6. isolates stale or standalone protected consumers before owner mutations;
7. requires a role-owned label before adopting or removing a same-name owner;
8. rejects unknown containers sharing the owner's actual network namespace;
9. validates consumer unit dependency and runtime exact-ID contract markers;
10. waits for Docker health before the systemd start job succeeds;
11. cooperates with consumer-side `BindsTo=` stop coupling;
12. stops and verifies protected consumers before removing the namespace owner.

Gluetun must run its entrypoint as root with network-administration
capabilities and access to `/dev/net/tun`. This role grants the normal Docker
default capability set plus `NET_ADMIN`, explicitly rather than using
`--privileged`.

The guarantee covers managed lifecycle operations and ordinary VPN tunnel
loss. Direct out-of-band commands such as `docker restart gluetun` bypass
systemd stop coupling and are outside the guarantee.

## Development

You can optionally install a Git pre-commit hook with:

```sh
just prek-install-git-pre-commit-hook
```
