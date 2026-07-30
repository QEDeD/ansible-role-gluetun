#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MASH project contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Verify rendered Gluetun fail-closed artifacts without a container runtime."""

from __future__ import annotations

import hashlib
import shlex
import sys
import tomllib
from pathlib import Path


API_KEY = "static-test-api-key-1234567890"
DIAGNOSTIC_ROUTES = [
    "GET /v1/version",
    "GET /v1/vpn/status",
    "GET /v1/openvpn/status",
    "GET /v1/dns/status",
    "GET /v1/updater/status",
    "GET /v1/publicip/ip",
]
EMPTY_PROXY_KEYS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "FTP_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "ftp_proxy",
]


def fail(message: str) -> None:
    raise AssertionError(message)


def parse_environment(path: Path) -> dict[str, str]:
    environment: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line:
            continue
        if "=" not in line:
            fail(f"{path}:{line_number}: environment line has no equals sign")
        key, value = line.split("=", 1)
        if not key or key in environment:
            fail(f"{path}:{line_number}: empty or duplicate environment key")
        environment[key] = value
    return environment


def shell_assignment(script: str, variable: str) -> str:
    prefix = f"{variable}="
    lines = [line for line in script.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        fail(f"expected one {variable} assignment, found {len(lines)}")
    parsed = shlex.split(lines[0][len(prefix) :])
    if len(parsed) != 1:
        fail(f"{variable} is not one safely quoted shell word")
    return parsed[0]


def verify_environment(rendered_path: Path) -> None:
    environment = parse_environment(rendered_path / "env")
    expected = {
        "VPN_SERVICE_PROVIDER": "protonvpn",
        "VPN_TYPE": "wireguard",
        "VPN_INTERFACE": "tun0",
        "OPENVPN_USER_SECRETFILE": "/run/secrets/openvpn_user",
        "OPENVPN_PASSWORD_SECRETFILE": "/run/secrets/openvpn_password",
        "OPENVPN_CLIENTCRT_SECRETFILE": "/run/secrets/openvpn_clientcrt",
        "OPENVPN_CLIENTKEY_SECRETFILE": "/run/secrets/openvpn_clientkey",
        "OPENVPN_ENCRYPTED_KEY_SECRETFILE": (
            "/run/secrets/openvpn_encrypted_key"
        ),
        "OPENVPN_KEY_PASSPHRASE_SECRETFILE": (
            "/run/secrets/openvpn_key_passphrase"
        ),
        "WIREGUARD_CONF_SECRETFILE": "/run/secrets/wg0.conf",
        "WIREGUARD_PRIVATE_KEY_SECRETFILE": (
            "/run/secrets/wireguard_private_key"
        ),
        "WIREGUARD_PRESHARED_KEY_SECRETFILE": (
            "/run/secrets/wireguard_preshared_key"
        ),
        "WIREGUARD_ADDRESSES_SECRETFILE": (
            "/run/secrets/wireguard_addresses"
        ),
        "WIREGUARD_ALLOWED_IPS": "0.0.0.0/0",
        "FIREWALL_ENABLED_DISABLING_IT_SHOOTS_YOU_IN_YOUR_FOOT": "on",
        "FIREWALL_DEBUG": "off",
        "FIREWALL_INPUT_PORTS": "",
        "FIREWALL_VPN_INPUT_PORTS": "",
        "FIREWALL_OUTBOUND_SUBNETS": "",
        "DNS_SERVER": "on",
        "DNS_ADDRESS": "127.0.0.1",
        "DNS_KEEP_NAMESERVER": "off",
        "DNS_UPSTREAM_RESOLVER_TYPE": "dot",
        "DNS_UPSTREAM_RESOLVERS": "cloudflare",
        "DNS_UPSTREAM_IPV6": "off",
        "HEALTH_SERVER_ADDRESS": "127.0.0.1:9999",
        "HEALTH_TARGET_ADDRESSES": "cloudflare.com:443,github.com:443",
        "HEALTH_ICMP_TARGET_IPS": "1.1.1.1,8.8.8.8",
        "HEALTH_RESTART_VPN": "on",
        "HTTP_CONTROL_SERVER_ADDRESS": "127.0.0.1:8000",
        "HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE": "{}",
        "HTTP_CONTROL_SERVER_AUTH_CONFIG_FILEPATH": (
            "/run/secrets/control-server-auth.toml"
        ),
        "HTTPPROXY": "off",
        "SHADOWSOCKS": "off",
        "VPN_PORT_FORWARDING": "off",
        "PPROF_ENABLED": "no",
        "UPDATER_PERIOD": "0",
        "PUID": "1000",
        "PGID": "1000",
        "TZ": "Etc/UTC",
        "SERVER_COUNTRIES": "Denmark,Sweden",
        "WIREGUARD_MTU": "1320",
    }
    if environment != expected:
        missing = sorted(expected.keys() - environment.keys())
        unexpected = sorted(environment.keys() - expected.keys())
        changed = sorted(
            key
            for key in expected.keys() & environment.keys()
            if expected[key] != environment[key]
        )
        fail(
            "rendered environment differs from the complete static contract: "
            f"missing={missing}, unexpected={unexpected}, changed={changed}"
        )
    if API_KEY in rendered_path.joinpath("env").read_text():
        fail("the control-server API key leaked into the environment file")


def verify_control_auth(rendered_path: Path) -> None:
    auth_path = rendered_path / "control-server-auth.toml"
    auth_bytes = auth_path.read_bytes()
    policy = tomllib.loads(auth_bytes.decode())
    expected_policy = {
        "roles": [
            {
                "name": "read-only-diagnostics",
                "routes": DIAGNOSTIC_ROUTES,
                "auth": "apikey",
                "apikey": API_KEY,
            }
        ]
    }
    if policy != expected_policy:
        fail("rendered control-server authentication policy is not exact")

    helper = rendered_path.joinpath("gluetun-container-helper").read_text()
    expected_hash = hashlib.sha256(auth_bytes).hexdigest()
    embedded_hash = shell_assignment(
        helper,
        "auth_config_expected_sha256",
    )
    if embedded_hash != expected_hash:
        fail(
            "helper authentication-policy hash does not match the rendered "
            "TOML bytes"
        )
    if API_KEY in helper:
        fail("the control-server API key leaked into the container helper")


def verify_helper(rendered_path: Path) -> None:
    helper = rendered_path.joinpath("gluetun-container-helper").read_text()
    required_fragments = [
        "# MASH-Role=Gluetun-container-helper",
        "is_full_container_id()",
        "discover_exact_owner_id()",
        "exact_container_id_is_absent()",
        "owner_identity_has_contract_labels()",
        "remove_owner_id()",
        "auth_config_is_expected()",
        '"$docker_command" container rm --force "$candidate_id"',
        '"$docker_command" start --attach "$owner_id"',
        "--cap-drop=ALL",
        "--device=$tun_device:$tun_device:rwm",
        "--network=$owner_network",
        "--dns=127.0.0.1",
        "--env-file=$environment_file",
        "--mount=type=bind,src=$data_path,dst=/gluetun",
        "--mount=type=bind,src=$secrets_path,dst=/run/secrets,readonly",
    ]
    for fragment in required_fragments:
        if fragment not in helper:
            fail(f"rendered helper is missing contract fragment: {fragment}")
    for proxy_key in EMPTY_PROXY_KEYS:
        if f"--env={proxy_key}=" not in helper:
            fail(f"rendered helper does not clear {proxy_key}")
    if "--publish" in helper or "--publish-all" in helper:
        fail("rendered helper unexpectedly publishes a host port")


def verify_unit(rendered_path: Path) -> None:
    unit_lines = rendered_path.joinpath("gluetun.service").read_text().splitlines()
    required_lines = [
        "# MASH-Role=Gluetun-namespace-owner",
        "RefuseManualStart=no",
        "RefuseManualStop=no",
        "Requires=docker.service",
        "After=docker.service",
        "Wants=qbittorrent.service",
        "RuntimeDirectory=gluetun-container",
        "ExecStartPre=/etc/systemd/system/gluetun-container-helper cleanup",
        "ExecStartPre=/etc/systemd/system/gluetun-container-helper create",
        "ExecStart=/etc/systemd/system/gluetun-container-helper start",
        "ExecStartPost=/etc/systemd/system/gluetun-container-helper health",
        "ExecStop=/etc/systemd/system/gluetun-container-helper stop",
        "ExecStopPost=/etc/systemd/system/gluetun-container-helper cleanup",
        "Restart=always",
    ]
    for line in required_lines:
        if line not in unit_lines:
            fail(f"rendered owner unit is missing exact line: {line}")


def verify_quiesce(rendered_path: Path) -> None:
    quiesce_lines = [
        line
        for line in rendered_path.joinpath(
            "gluetun-quiesce.conf"
        ).read_text().splitlines()
        if line
    ]
    expected_lines = [
        "# MASH-Role=Gluetun-quiesce",
        "[Unit]",
        "RefuseManualStart=yes",
        "RefuseManualStop=no",
        "[Service]",
        "Restart=no",
        "RestartForceExitStatus=",
        "RestartPreventExitStatus=",
        "ExecCondition=",
        "ExecStartPre=",
        "ExecStart=",
        "ExecStart=/bin/false",
        "ExecStartPost=",
        "ExecReload=",
        "ExecStop=",
        "ExecStop=/bin/true",
        "ExecStopPost=",
    ]
    if quiesce_lines != expected_lines:
        fail("rendered persistent quiesce is not the exact inert contract")


def verify_transaction_sources() -> None:
    role_path = Path(__file__).resolve().parents[1]
    release = role_path.joinpath("tasks/release_quiesce.yml").read_text()
    final_verifier = role_path.joinpath("tasks/verify_final_unit.yml").read_text()
    absent_verifier = role_path.joinpath(
        "tasks/verify_absent_unit.yml"
    ).read_text()
    guarded_absent_verifier = role_path.joinpath(
        "tasks/verify_guarded_absent_unit.yml"
    ).read_text()
    quiesce = role_path.joinpath("tasks/quiesce.yml").read_text()
    lifecycle_validation = role_path.joinpath(
        "tasks/validate_lifecycle.yml"
    ).read_text()
    install = role_path.joinpath("tasks/install.yml").read_text()
    uninstall = role_path.joinpath("tasks/uninstall.yml").read_text()

    release_fragments = [
        "Release the persistent Gluetun quiesce transactionally",
        "Verify no shadow Gluetun unit precedes uninstall guard release",
        "Verify the effective finalized Gluetun unit",
        "Verify the Gluetun unit is absent after uninstall release",
        "rescue:",
        "Restore the persistent Gluetun release marker after release failure",
        "templates/systemd/gluetun-quiesce.conf.j2",
        "Verify restored Gluetun quiescing when a final unit was expected",
        "tasks/verify_quiesce_unit.yml",
        "tasks/verify_absent_unit.yml",
        "intentional unit removal it may be only a durable release marker",
    ]
    for fragment in release_fragments:
        if fragment not in release:
            fail(f"transactional quiesce release is missing: {fragment}")

    final_properties = [
        "--property=LoadState",
        "--property=FragmentPath",
        "--property=Type",
        "--property=Restart",
        "--property=RestartForceExitStatus",
        "--property=RestartPreventExitStatus",
        "--property=RefuseManualStart",
        "--property=RefuseManualStop",
        "--property=DropInPaths",
        "--property=RuntimeDirectory",
        "--property=RuntimeDirectoryMode",
        "--property=ExecStartPre",
        "--property=ExecStart",
        "--property=ExecStartPost",
        "--property=ExecStop",
        "--property=ExecStopPost",
        "gluetun_final_dropin_paths_result.stdout | trim | length == 0",
        "gluetun_final_runtime_directory_mode_result.stdout | trim == '0700'",
    ]
    for fragment in final_properties:
        if fragment not in final_verifier:
            fail(f"effective final-unit verifier is missing: {fragment}")

    absent_properties = [
        "--property=LoadState",
        "--property=FragmentPath",
        "--property=DropInPaths",
        "--property=ActiveState",
        "--property=Job",
        "--property=MainPID",
        "--property=ControlPID",
        "gluetun_absent_load_state_result.stdout | trim == 'not-found'",
        "gluetun_absent_fragment_path_result.stdout | trim | length == 0",
        "gluetun_absent_dropin_paths_result.stdout | trim | length == 0",
        "gluetun_absent_active_state_result.stdout",
        "gluetun_absent_job_result.stdout",
        "gluetun_absent_process_ids_result.stdout_lines",
    ]
    for fragment in absent_properties:
        if fragment not in absent_verifier:
            fail(f"effective absent-unit verifier is missing: {fragment}")

    guarded_absent_properties = [
        "--property=LoadState",
        "--property=FragmentPath",
        "--property=DropInPaths",
        "gluetun_guarded_absent_load_state_result.stdout | trim == 'not-found'",
        "gluetun_guarded_absent_fragment_path_result.stdout",
        "gluetun_guarded_absent_dropin_paths_result.stdout.split()",
        "== [gluetun_guarded_absent_expected_dropin_path]",
        "Removing the role-owned Gluetun unit revealed an effective same-name",
    ]
    for fragment in guarded_absent_properties:
        if fragment not in guarded_absent_verifier:
            fail(f"guarded absent-unit verifier is missing: {fragment}")

    quiesce_fragments = [
        "--property=RefuseManualStop",
        "gluetun_quiesce_dropin_paths_result.stdout.split()",
        "== [gluetun_quiesce_dropin_path]",
    ]
    for fragment in quiesce_fragments:
        if fragment not in quiesce:
            fail(f"effective quiesce verifier is missing: {fragment}")

    lifecycle_fragments = [
        "--property=LoadState",
        "--property=FragmentPath",
        "--property=ActiveState",
        "--property=Job",
        "--property=MainPID",
        "--property=ControlPID",
        "tasks/evaluate_effective_unit_fragment_contract.yml",
        "gluetun_effective_unit_fragment_contract_valid | bool",
    ]
    for fragment in lifecycle_fragments:
        if fragment not in lifecycle_validation:
            fail(f"pre-mutation effective-unit validation is missing: {fragment}")

    if "gluetun_quiesce_release_final_unit_expected: true" not in install:
        fail("installation does not require final effective-unit verification")
    if "gluetun_quiesce_release_final_unit_expected: false" not in uninstall:
        fail("uninstall does not declare the intentionally absent final unit")
    if (
        "in gluetun_uninstall_owned_consumer_unit_stop_targets_list"
        not in uninstall
    ):
        fail("uninstall can stop an unattested same-name consumer unit")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {Path(sys.argv[0]).name} RENDERED-DIRECTORY")
    rendered_path = Path(sys.argv[1])
    if not rendered_path.is_dir():
        raise SystemExit(f"Not a rendered directory: {rendered_path}")
    verify_environment(rendered_path)
    verify_control_auth(rendered_path)
    verify_helper(rendered_path)
    verify_unit(rendered_path)
    verify_quiesce(rendered_path)
    verify_transaction_sources()


if __name__ == "__main__":
    main()
