#!/bin/sh
# SPDX-FileCopyrightText: 2026 MASH project contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

set -eu

test_output_root=$(mktemp -d /tmp/mash-gluetun-static-test.XXXXXXXX)
test_rendered_path="$test_output_root/rendered"
test_ansible_tmp_path="$test_output_root/ansible-tmp"

cleanup() {
  rm -rf -- "$test_output_root"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$test_ansible_tmp_path"

ANSIBLE_LOCAL_TEMP="$test_ansible_tmp_path" \
ANSIBLE_REMOTE_TEMP="$test_ansible_tmp_path" \
  ansible-playbook \
    --inventory localhost, \
    --connection local \
    --extra-vars "gluetun_static_test_output_path=$test_rendered_path" \
    tests/static-render.yml

/bin/sh -n "$test_rendered_path/gluetun-container-helper"
/usr/bin/python3 tests/verify-static.py "$test_rendered_path"
