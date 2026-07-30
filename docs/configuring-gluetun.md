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

# Store a high-entropy value in encrypted inventory.
gluetun_control_server_auth_api_key_secret: ""
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

The role writes secrets and the generated control-server authentication file
with mode `0600`, suppresses Ansible logging and diffs for secret tasks, and
mounts the secret directory read-only at `/run/secrets`. The generated
environment file contains only the authentication-file path, never the API
key. A namespace-sharing protected container does not inherit Gluetun's
filesystem mounts and cannot read that file.

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
8. verify `io.mash.gluetun.fail-closed-contract=v1` before joining it;
9. stop when the owner unit stops and recreate after the owner container ID
   changes;
10. include these exact unit contract lines:

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

This directs the protected service to Gluetun's loopback DNS forwarder. The
owner is also created with `--dns=127.0.0.1`, preventing Docker's embedded
resolver from becoming a host-side fallback. Runtime tests must still prove
this behavior against the pinned Docker and Gluetun versions.

Configure the protected unit and container identities together:

```yaml
gluetun_protected_consumers_list:
  - systemd_service_name: qbittorrent.service
    container_name: qbittorrent
    systemd_unit_role_marker: "# MASH-Role=qBittorrent"
```

The role marker must be a literal line rendered by the consumer role. Gluetun
will not use an existing consumer unit as a stop target until the file is a
regular non-symlink and contains that marker.

Docker container and network names used by this contract cannot consist only
of lowercase hexadecimal characters, because Docker also accepts bare
hexadecimal prefixes as object IDs.

The Gluetun unit derives its `Wants=` relationships from this list. The
consumer-side `BindsTo=` and `After=` relationship provides ordering and stop
coupling, including unexpected owner failure.

## Integrator sequencing

This role runs an isolation gate before changing paths, images, networks or
units. Before that gate, it compares the intended unit's disk presence with
systemd's effective load state and fragment path. A loaded vendor, transient
or deleted-but-cached same-name fragment is rejected. A `not-found` unit is
accepted only with an empty fragment path, an inactive or failed state, no
queued job and zero main/control process IDs; an existing recognized role
fragment may then be reloaded under the controlled quiesce.

The isolation gate resolves exact names to full IDs, then inspects those
immutable IDs. A consumer is preserved only if it is absent, stopped, or its
exact network mode is `container:<current-owner-ID>` and that exact owner is
running. Any running standalone, renamed, stale-owner, or stopped-owner
consumer has its configured systemd unit, declared name, and resolved ID
stopped. The role proves the unit inactive and both the original ID and current
exact name no longer running before proceeding.

Docker query or inspection uncertainty first triggers conservative consumer
isolation and only then fails the run. Errors are never interpreted as
container absence. An idempotent run does not interrupt a positively verified
consumer already attached to the exact current owner ID.

The owner carries fixed identity and versioned fail-closed contract labels.
Before preserving it, the role attests its tag-and-digest image reference and
local image content ID, complete effective `Config.Env`, network, loopback DNS,
user, non-privileged mode, capabilities, TUN device, IPv6 sysctls, mounts and
absence of published ports. The environment expectation models Docker's
key-based merge of the pinned image's complete default environment with every
role-supplied value, including explicitly empty uppercase and lowercase proxy
variables. Duplicate keys, omitted inherited defaults, changed values and
additional variables all invalidate the owner contract. The immutable default
list is tied by length and hash to the v3.41.2 Dockerfile and final-image
`PATH`; a version upgrade must update that evidence deliberately.

An identity-labelled owner that fails this contract is replaced only by its
captured full ID after protected consumers are isolated. A same-name container
without the identity label is neither adopted nor removed.

The systemd helper discovers the stable name only to capture and compare a
full container ID. Creation, start, health, stop and cleanup then operate on
that immutable ID, retry exact-ID cleanup to convergence and refuse an
unverified same-name replacement.

The qBittorrent or other consumer role must render this safe unit before the
Gluetun role renders its reverse `Wants=` relationship. Service-manager
priority remains owner first and consumer second: `Wants=` pulls the consumer
in, while its `After=` waits for the owner's health-gated start job.

When a current owner exists, the role also inventories all running Docker
containers and compares their actual network sandbox and `container:` network
mode. It rejects unknown or multiple namespace consumers. Such namespace
consumers are not Docker bridge endpoints and therefore require this separate
registry check.

## Persistent lifecycle quiesce and recovery

Before replacing or uninstalling an owner managed by an existing unit, the role
installs a fixed role-marked drop-in at
`/etc/systemd/system/gluetun.service.d/zzzz-mash-fail-closed-quiesce.conf`.
The drop-in refuses manual starts, disables restart, clears every lifecycle
command and substitutes inert start and stop commands. The role reloads
systemd and verifies the effective policy, queued job state and process IDs
before it stops or removes the captured owner container ID.

The drop-in is deliberately persistent. If Ansible, the controller or the host
fails after quiescing, the old unit cannot restart the namespace owner behind
the role's back. A later run accepts the guard only when its path is a regular
non-symlink and its role marker is intact, then resumes installation or
uninstall recovery. The effective quiesced unit must contain exactly this one
drop-in, refuse manual starts while still allowing the role to stop it, clear
all other lifecycle commands, and expose only inert `/bin/false` start and
`/bin/true` stop commands.

Installation removes the guard only after the final owner unit has been
rendered and systemd reloaded. It then attests the effective fragment path,
absence of all drop-ins, manual-start and manual-stop policy, restart policy,
runtime directory and mode, and exact helper command paths and arguments. This
attestation also runs on a fresh installation where no earlier guard existed,
so a stale external drop-in cannot silently alter the new service. A failure
restores the guard, reloads systemd, verifies the effective inert policy and
leaves the stack offline.

Uninstall removes the role unit only after protected consumers and the owner
are proven isolated. While the guard is still present, it verifies that no
lower-priority same-name unit or additional drop-in became effective. After
guard removal and reload, it requires `LoadState=not-found` with empty fragment
and drop-in paths, an inactive or failed state, no queued job and zero process
IDs. A failed release restores the owned drop-in as a durable retry marker.
With no base unit that marker is not described as an effective guard, but the
already-proven owner and consumer isolation remains intact. These failures
affect only this service stack.

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

The loopback control server uses an API-key role limited to `GET` requests for
version, VPN, OpenVPN, DNS and updater status and public IP. No `PUT` or
settings route is assigned. Loopback belongs to the shared network namespace,
so the protected process can reach the listener. It does not inherit Gluetun's
filesystem mounts and therefore cannot read the mode-`0600` key file unless
the key is separately compromised or deliberately supplied. The API is not
published on the host. Operator diagnostics can retain local Web UI access
through the explicitly allowed Traefik peer and can perform authenticated
read-only control queries from within the owner when needed.

Runtime validation must prove unauthenticated and wrong-key requests,
including mutation attempts, are rejected by pinned Gluetun v3.41.2. Static
tests only prove the rendered TOML routes, API-key separation and exact
authentication-policy hash consumed by the lifecycle helper.

On uninstall, the role never force-disconnects another container, including a
configured known peer. If any endpoint remains, it retains the network and
emits a runtime warning. It also refuses to remove the owner while any
unconfigured running namespace consumer remains, and it independently stops,
removes, and proves the originally resolved owner ID absent even if the
systemd unit is missing or its cleanup command failed. A configured service
name is used as a stop target only when its real unit file was read and its
role marker validated; a missing file cannot redirect the role to a vendor or
otherwise foreign same-name service. The role still proves every configured
service inactive and separately proves that the stable container name remains
absent, without deleting an unverified replacement.

## Failure behaviour

After the initial health gate succeeds, an ordinary VPN tunnel loss leaves
Gluetun's firewall policies in place while Gluetun attempts internal recovery.
The protected process may continue running and its local Web UI may remain
reachable, but ordinary non-local Internet traffic has no host-network
fallback and is dropped. This is what “close down” means in this design: the
service is isolated from the Internet, not necessarily stopped.

The Gluetun firewall is the Internet kill switch. Docker health is a startup
readiness gate, and systemd `BindsTo=` handles owner-unit lifecycle; neither is
a substitute for the firewall during an in-process tunnel outage.

There is an unavoidable shared-namespace boundary. Gluetun must permit one or
more provider bootstrap/control-plane tuples—destination IP, port and
protocol—outside the tunnel so it can establish and maintain the VPN. Its
namespace firewall cannot distinguish Gluetun's packets from packets created
by another process in the same namespace. The managed health gate prevents the
protected service from running during initial bootstrap, but a malicious or
compromised protected process present during later recovery could deliberately
send to an allowed tuple. The fail-closed claim covers ordinary application
traffic and ordinary tunnel loss; it is not an exfiltration boundary against a
hostile namespace peer.

The initial firewall-enable path in Gluetun can restore firewall policies to
`ACCEPT` if setup fails part-way. The role prevents exposure to that path by
requiring owner health before a protected service starts and by stopping
protected services before managed owner restart or removal. The persistent
quiesce prevents an interrupted owner replacement from silently restarting an
old unit before a later run recovers it.

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
- arbitrary control-server authentication or additional routes;
- custom OpenVPN configuration files;
- multiple protected services sharing one owner.

These require separate design and runtime evidence rather than generic escape
hatches.

The guarantee also excludes a malicious or compromised protected process
abusing an allowed provider bootstrap/control-plane tuple, a compromised
Gluetun process with `NET_ADMIN`, external firewall flushing, kernel defects
and out-of-band Docker lifecycle operations.

## Uninstall and retention

Uninstall:

1. stops configured protected services;
2. stops and removes the namespace owner;
3. removes rendered environment, resolver and secret copies;
4. leaves all peer attachment ownership to the integrating role;
5. removes the bridge only when no endpoints remain;
6. retains the bridge with a warning when any endpoint remains;
7. retains non-empty Gluetun state under `gluetun_data_path`.

The role never recursively deletes retained state or protected-service data.
