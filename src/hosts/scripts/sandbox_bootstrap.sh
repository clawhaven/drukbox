#!/usr/bin/env bash
# Sandbox host first-boot bootstrap. Delivered to the VM at create time via the
# VM provider's setup-script mechanism (exe.dev's --setup-script today).
#
# The VM brings itself onto the tailnet and exits. Drukbox observes the new
# device by polling Tailscale's API from outside; no callback into drukbox
# is made from this script, and drukbox is never reachable from the box.
#
# Required env:
#   TAILSCALE_AUTHKEY
#   TAILSCALE_HOSTNAME
#
# Optional env:
#   TAILSCALE_ADVERTISE_TAGS              (default: tag:sandbox)
#   TAILSCALE_LOGIN_SERVER                (default: unset)

set -euo pipefail

state_dir=/var/lib/sandbox
done_path="$state_dir/bootstrap.done"

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi

  if ! command -v sudo >/dev/null 2>&1; then
    echo "Sandbox bootstrap requires root or passwordless sudo." >&2
    exit 1
  fi

  sudo -n "$@"
}

run_privileged install -d -m 755 -o "$(id -u)" -g "$(id -g)" "$state_dir"

# Defensive against re-runs: --setup-script is documented as run-once, and the
# legacy in-image systemd unit (if present on transitional images) also gates on
# this flag. Either path converges on the same end state.
if [[ -f "$done_path" ]]; then
  exit 0
fi

require_var() {
  if [[ -z "${!1:-}" ]]; then
    echo "Sandbox bootstrap requires $1 to be set." >&2
    exit 1
  fi
}

require_var TAILSCALE_AUTHKEY
require_var TAILSCALE_HOSTNAME

advertise_tags="${TAILSCALE_ADVERTISE_TAGS:-tag:sandbox}"

run_privileged systemctl enable --now tailscaled.service

tailscale_running() {
  tailscale status --json 2>/dev/null | jq -e '.BackendState == "Running"' >/dev/null
}

if ! tailscale_running; then
  tailscale_args=(
    up
    "--authkey=$TAILSCALE_AUTHKEY"
    --accept-dns=true
    --ssh
    "--hostname=$TAILSCALE_HOSTNAME"
    --reset
  )
  if [[ -n "$advertise_tags" ]]; then
    tailscale_args+=("--advertise-tags=$advertise_tags")
  fi
  if [[ -n "${TAILSCALE_LOGIN_SERVER:-}" ]]; then
    tailscale_args+=("--login-server=$TAILSCALE_LOGIN_SERVER")
  fi
  run_privileged tailscale "${tailscale_args[@]}"
fi

touch "$done_path"
