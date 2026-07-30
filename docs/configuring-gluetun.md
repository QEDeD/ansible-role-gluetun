<!--
SPDX-FileCopyrightText: 2026 MASH project contributors

SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Configuring Gluetun

This role implements a narrow network-namespace owner for one protected
service. It is not a general Gluetun option passthrough.

## Required configuration

Choose a provider and protocol and provide protocol credentials through native
secret files:

```yaml
gluetun_vpn_service_provider: protonvpn
gluetun_vpn_type: wireguard

# Supply these from encrypted inventory; the examples are intentionally empty.
gluetun_wireguard_private_key_secret: ""
gluetun_wireguard_addresses_secret: ""
```

Alternatively, supply a full WireGuard configuration:

```yaml
gluetun_wireguard_configuration_secret: ""
```

Do not combine a full WireGuard configuration with discrete WireGuard secret
variables. Values in `wg0.conf` take precedence upstream, so the role rejects
that ambiguous state.

For OpenVPN, the username and password must either both be supplied or both be
empty:

```yaml
gluetun_vpn_service_provider: private internet access
gluetun_vpn_type: openvpn
gluetun_openvpn_user_secret: ""
gluetun_openvpn_password_secret: ""
```

The role writes secrets with mode `0600`, suppresses Ansible logging and diffs
for secret tasks, and mounts the secret directory read-only at `/run/secrets`.
The generated environment file contains no secret values.

## Provider selection settings

Non-secret provider settings use a typed mapping:

```yaml
gluetun_vpn_provider_environment_variables_custom:
  SERVER_COUNTRIES: Denmark,Sweden
  WIREGUARD_MTU: "1320"
```

Only keys listed in
`gluetun_vpn_provider_environment_variable_names_allowed` are accepted.
Firewall, DNS, control-server, proxy, command-hook and port-forwarding settings
cannot be injected through this mapping.

## Protected-service integration

The protected service must:

1. resolve the current Gluetun owner and use
   `--network=container:<full-gluetun-container-ID>`;
2. have no own Docker network, additional networks or published ports;
3. omit Docker options incompatible with container networking, including
   `--hostname` and `--dns`;
4. mount `gluetun_companion_resolv_conf_path` read-only at
   `/etc/resolv.conf`;
5. require and order itself after the Gluetun systemd unit;
6. verify the current owner container is healthy before creation;
7. resolve and use the owner's full container ID at runtime, rather than
   trusting a mutable owner name;
8. stop when the owner unit stops and recreate after the owner container ID
   changes;
9. include these exact unit contract lines:

   ```systemd
   BindsTo=gluetun.service
   After=gluetun.service
   # MASH-NetworkNamespaceOwner=gluetun
   # MASH-NetworkNamespaceIdentity=resolved-full-container-id
   ```

The identity marker is literal capability metadata. It asserts that the unit
uses the runtime exact-ID resolver; it is not replaced with an ID.

The generated resolver contains only:

```text
nameserver 127.0.0.1
options ndots:0
```

This directs the protected service to Gluetun's loopback DNS forwarder. DNS
cannot fall back to Docker's or the host's resolver.

Configure the protected unit and container identities together:

```yaml
gluetun_protected_consumers_list:
  - systemd_service_name: qbittorrent.service
    container_name: qbittorrent
```

Docker container and network names used by this contract cannot consist only
of lowercase hexadecimal characters, because Docker also accepts bare
hexadecimal prefixes as object IDs.

The Gluetun unit derives its `Wants=` relationships from this list. The
consumer-side `BindsTo=` and `After=` relationship provides ordering and stop
coupling, including unexpected owner failure.

## Integrator sequencing

This role runs an isolation gate before changing paths, images, networks or
units. It resolves exact names to full IDs, then inspects those immutable IDs.
A consumer is preserved only if it is absent, stopped, or its exact network
mode is `container:<current-owner-ID>` and that exact owner is running. Any
running standalone, renamed, stale-owner, or stopped-owner consumer has its
configured systemd unit, declared name, and resolved ID stopped. The role
proves the unit inactive and both the original ID and current exact name no
longer running before proceeding.

Docker query or inspection uncertainty first triggers conservative consumer
isolation and only then fails the run. Errors are never interpreted as
container absence. An idempotent run does not interrupt a positively verified
consumer already attached to the exact current owner ID.

The owner container carries a fixed role-owned label. A same-name container
without the exact label is not adopted or removed: configured consumers are
isolated first and the run then refuses further owner mutation.

The qBittorrent or other consumer role must render this safe unit before the
Gluetun role renders its reverse `Wants=` relationship. Service-manager
priority remains owner first and consumer second: `Wants=` pulls the consumer
in, while its `After=` waits for the owner's health-gated start job.

When a current owner exists, the role also inventories all running Docker
containers and compares their actual network sandbox and `container:` network
mode. It rejects unknown or multiple namespace consumers. Such namespace
consumers are not Docker bridge endpoints and therefore require this separate
registry check.

## Dedicated bridge and Traefik

Gluetun owns one dedicated IPv4 bridge. Do not reuse MASH's common reverse
proxy network and do not attach unrelated services.

Traefik may be attached as a known peer so a protected Web UI remains
available for diagnostics while Internet egress is blocked:

```yaml
gluetun_container_network_known_peer_containers_list:
  - traefik
```

The Traefik role or playbook integration owns attachment. This role does not
attach peers during installation. The dedicated bridge must contain only
Gluetun and explicitly configured proxy peers. The bridge carries a
role-owned label; an existing unlabelled or differently labelled network is
never adopted or removed.

Pinned Gluetun v3.41.2 automatically accepts INPUT from every detected local
subnet. `gluetun_firewall_input_ports` is therefore fixed empty and is not an
effective per-port diagnostic boundary. The dedicated bridge, exact endpoint
allowlist, and approved Traefik peer are the local diagnostic trust boundary:
the host bridge gateway and Traefik may reach every namespace listener bound
to the bridge address. No host ports are published, and this local reachability
does not permit protected-service Internet egress. Gluetun's DNS, health and
control listeners remain bound to loopback.

On uninstall, the role disconnects only explicitly listed known peers. It
never force-disconnects unknown endpoints. If an unknown endpoint remains,
network deletion does not converge and the role retains the network with a
runtime warning. It also refuses to remove the owner while any unconfigured
running namespace consumer remains, and it independently stops, removes, and
proves both the stable owner name and originally resolved owner ID absent even
if the systemd unit is missing or its cleanup command failed.

## Failure behaviour

After the initial health gate succeeds, an ordinary VPN tunnel loss leaves
Gluetun's firewall policies in place while Gluetun attempts internal recovery.
The protected process may continue running and its local Web UI may remain
reachable, but new non-local Internet traffic is dropped.

The Gluetun firewall is the Internet kill switch. Docker health is a startup
readiness gate, and systemd `BindsTo=` handles owner-unit lifecycle; neither is
a substitute for the firewall during an in-process tunnel outage.

The initial firewall-enable path in Gluetun can restore firewall policies to
`ACCEPT` if setup fails part-way. The role prevents exposure to that path by
requiring owner health before a protected service starts and by stopping
protected services before managed owner restart or removal.

Do not run direct out-of-band commands such as:

```text
docker restart gluetun
```

Such commands bypass systemd stop propagation and are outside the fail-closed
guarantee. Use the managed systemd services.

## Deliberate limitations

The initial role does not support:

- IPv6;
- additional Docker networks;
- host-published ports;
- HTTP or Shadowsocks proxies;
- VPN-side port forwarding;
- VPN-side firewall input or outbound-subnet exceptions;
- custom firewall rules;
- VPN up/down command hooks;
- arbitrary Docker arguments or mounts;
- custom control-server authentication or routes;
- multiple protected services sharing one owner.

These require separate design and runtime evidence rather than generic escape
hatches.

The guarantee also excludes a compromised Gluetun process with `NET_ADMIN`,
external firewall flushing, kernel defects and out-of-band Docker lifecycle
operations.

## Uninstall and retention

Uninstall:

1. stops configured protected services;
2. stops and removes the namespace owner;
3. removes rendered environment, resolver and secret copies;
4. disconnects only configured known network peers;
5. removes the bridge only when no endpoints remain;
6. retains non-empty Gluetun state under `gluetun_data_path`.

The role never recursively deletes retained state or protected-service data.
