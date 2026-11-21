#!/usr/bin/env bash
#
# ExecStart of the application unit: start the compose project, wait until every
# container of the declared services is ready, signal READY=1 to systemd, then stay
# alive as long as those containers run.

set -euo pipefail

TIMEOUT="${TIMEOUT:-300}"
PULL_TIMEOUT="${PULL_TIMEOUT:-600}"
INTERVAL="${INTERVAL:-5}"

# Exit code of a start that times out. The unit restarts on it (RestartForceExitStatus),
# since a slow dependency may be ready on the next try. Any other failure exits 1.
EXIT_TIMEOUT=75

# Each phase pushes the systemd start deadline to its own limit + 30s from now, so this
# script always gives up first and logs why.

# Pull the images first, on a separate budget: a slow pull must not shorten the wait
# for the containers. When the pull fails or times out, the start continues: `up` uses
# the images already on the host, and pulls only the images that are missing.
systemd-notify EXTEND_TIMEOUT_USEC=$(((PULL_TIMEOUT + 30) * 1000000)) || true
PULL_STATUS=0
timeout --kill-after=10 "$PULL_TIMEOUT" podman-compose --no-ansi pull || PULL_STATUS=$?
if [ "$PULL_STATUS" -eq 124 ] || [ "$PULL_STATUS" -eq 137 ]; then
  echo "podman-compose pull did not return after ${PULL_TIMEOUT}s, starting with the images already on the host."
elif [ "$PULL_STATUS" -ne 0 ]; then
  echo "podman-compose pull failed (code ${PULL_STATUS}), starting with the images already on the host."
fi

# Every delay below counts from here.
systemd-notify EXTEND_TIMEOUT_USEC=$(((TIMEOUT + 30) * 1000000)) || true
SECONDS=0

# Every container that `up` creates gets the label UNIT_LABEL, through --podman-run-args
# (podman-compose adds them to the `podman create` of each service). A one-off container
# created by `podman-compose run` (an interactive shell, a migration, a long command)
# copies the service labels and joins the project pod, but not this label: it is
# neither waited for nor watched, and keeps running on the old image until it exits.
UNIT="${UNIT:-$(basename "$0" .sh)}"
UNIT_LABEL="suitenumerique.st.unit=${UNIT}"

# Inspect every container in CONTAINERS. Set READY to the number of ready containers,
# and PENDING to a "name (state, health)" entry for each container that is not ready.
# Exit when a container has exited with a non-zero code.
#
# One inspection gives the state, the probe and the health, so a failed inspection
# leaves STATE empty and the container pending. PROBE is "none" when the container has
# no probe (none declared, or `healthcheck: disable: true`, which podman stores as
# ["NONE"]): the container is ready once running, whatever `podman ps` shows in its
# health column (it reads the healthcheck log, which podman stamps "reset" on every
# start, probe or not). With a probe, the container is ready only once `healthy`:
# podman omits the health when it cannot read the healthcheck log, and the container
# then stays pending.
INSPECT_FORMAT='{{.Name}} {{.State.Status}} {{.State.ExitCode}} '\
'{{$p := "none"}}{{with .Config.Healthcheck}}{{range $i, $t := .Test}}'\
'{{if and (eq $i 0) (ne $t "NONE")}}{{$p = "probe"}}{{end}}{{end}}{{end}}{{$p}} '\
'{{if .State.Health}}{{.State.Health.Status}}{{end}}'

check_containers() {
  READY=0
  PENDING=()
  local c NAME STATE EXIT_CODE PROBE HEALTH
  for c in "${CONTAINERS[@]}"; do
    NAME="" STATE="" EXIT_CODE="" PROBE="" HEALTH=""
    read -r NAME STATE EXIT_CODE PROBE HEALTH < <(podman inspect --format "$INSPECT_FORMAT" "$c" 2>/dev/null) || true
    NAME="${NAME:-$c}"
    [ "$PROBE" = "probe" ] && HEALTH="${HEALTH:-unknown}"

    if [ "$STATE" = "exited" ] && [ "$EXIT_CODE" != "0" ]; then
      echo "Container ${NAME} exited with code ${EXIT_CODE}, aborting."
      systemd-notify --status="Error: container ${NAME} exited with code ${EXIT_CODE}"
      exit 1
    fi

    if [ "$STATE" = "exited" ] || { [ "$STATE" = "running" ] && { [ "$PROBE" = "none" ] || [ "$HEALTH" = "healthy" ]; }; }; then
      READY=$((READY + 1))
    else
      PENDING+=("${NAME} (${STATE:-unknown}${HEALTH:+, $HEALTH})")
    fi
  done
}

report_pending() {
  if [ "${#PENDING[@]}" -eq 0 ]; then
    echo "$1, no created container is pending:"
    podman-compose --no-ansi ps || true
    systemd-notify --status="Error: $1, no created container is pending"
    return
  fi
  echo "$1, containers not ready:"
  printf '  %s\n' "${PENDING[@]}"
  systemd-notify --status="Error: $1, waiting for ${PENDING[*]}"
}

list_containers() {
  local ids
  ids=$(podman ps -a -q --no-trunc --filter "label=${UNIT_LABEL}")
  CONTAINERS=()
  [ -n "$ids" ] && mapfile -t CONTAINERS <<<"$ids"
  TOTAL=${#CONTAINERS[@]}
}

# Start the compose in detached mode. `up -d` waits for each `depends_on: condition:
# service_healthy` with no limit, and pulls the images that are missing, so bound it:
# it must fail here, with the state of the containers, rather than when systemd kills
# the unit.
UP_STATUS=0
timeout --kill-after=10 "$TIMEOUT" \
  podman-compose --podman-run-args="--sdnotify ignore --label=${UNIT_LABEL}" --no-ansi up -d || UP_STATUS=$?

if [ "$UP_STATUS" -eq 124 ] || [ "$UP_STATUS" -eq 137 ]; then
  echo "podman-compose up did not return after ${TIMEOUT}s."
  list_containers
  check_containers
  report_pending "Timeout after ${SECONDS}s"
  exit "$EXIT_TIMEOUT"
elif [ "$UP_STATUS" -ne 0 ]; then
  exit "$UP_STATUS"
fi

# Let podman register the containers.
sleep 2

list_containers

if [ "$TOTAL" -eq 0 ]; then
  echo "No containers found after compose up, aborting."
  exit 1
fi

# `up -d` can exit 0 having created only SOME of the services: it gives up on a
# depends_on it cannot satisfy and skips that service silently. Counting only what
# it created would then report "all containers healthy" with half the stack down,
# so compare against what the compose file declares. Best effort: when the service
# list cannot be read, keep going rather than refuse to start.
DECLARED=$(podman-compose --no-ansi config --services 2>/dev/null | grep -c '[^[:space:]]' || true)
if [ -n "${DECLARED:-}" ] && [ "$DECLARED" -gt "$TOTAL" ]; then
  echo "compose declares $DECLARED services but only $TOTAL container(s) exist:"
  podman-compose --no-ansi ps || true
  echo "a service was never created (check its image tag and its depends_on), aborting."
  exit 1
fi

while true; do
  check_containers

  if [ "${#PENDING[@]}" -eq 0 ]; then
    break
  fi

  if [ "$SECONDS" -ge "$TIMEOUT" ]; then
    report_pending "Timeout after ${SECONDS}s"
    exit "$EXIT_TIMEOUT"
  fi

  systemd-notify --status="Starting: ${READY}/${TOTAL} ready (${SECONDS}s), waiting for ${PENDING[*]}"
  sleep "$INTERVAL"
done

systemd-notify --ready --status="All ${TOTAL} containers ready"

# Wait for any still-running container to stop, then exit with failure
# so systemd knows the service is no longer healthy.
RUNNING=()
for c in "${CONTAINERS[@]}"; do
  STATE=$(podman inspect --format "{{.State.Status}}" "$c" 2>/dev/null || true)
  [ "$STATE" = "running" ] && RUNNING+=("$c")
done
[ ${#RUNNING[@]} -gt 0 ] && podman wait --condition=stopped "${RUNNING[@]}"
exit 1
