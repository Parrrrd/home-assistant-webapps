#!/bin/sh
set -eu

test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT HUP INT TERM

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WEBAPP_UPDATER_LIBRARY_MODE=true . "$script_dir/rootfs/run.sh"

UPDATE_BACKUP_PASSWORD_FILE="$test_dir/backup-password"
UPDATE_BACKUP_INDEX="$test_dir/pre-update-backups.json"
AUTO_UPDATE_POLICY_FILE="$test_dir/native-auto-update-policy"
MANAGED_APPS_FALLBACK="$test_dir/managed-apps.json"
printf '%s' '[{"local_slug":"local_demo"},{"local_slug":"webapp_updater"}]' > "$MANAGED_APPS_FALLBACK"
post_calls=0
auto_update_calls=0

printf '%s\n' 'version: "1.2.3"' > "$test_dir/config.yaml"
[ "$(version_from "$test_dir")" = "1.2.3" ]
printf '%s\r\n' "  version: '1.2.4' # legacy format" > "$test_dir/config.yaml"
[ "$(version_from "$test_dir")" = "1.2.4" ]
version_is_newer "1.2.4" "1.2.3"
! version_is_newer "1.2.3" "1.2.4"

log() { :; }

supervisor_post_file() {
  endpoint=$1
  payload_file=$2
  [ "$endpoint" = "/backups/new/partial" ]
  post_calls=$((post_calls + 1))
  jq -e --arg addon "local_demo" '
    .homeassistant == false
    and .addons == [$addon]
    and .compressed == true
    and .background == false
    and (.password | type == "string" and length > 30)
  ' "$payload_file" >/dev/null
  printf '%s' '{"data":{"slug":"backup_demo_001"}}'
}

supervisor_get() {
  case "$1" in
    /backups/backup_demo_001/info)
      printf '%s' '{"data":{"content":{"addons":["local_demo"]}}}'
      ;;
    /addons/local_demo/info|/addons/webapp_updater/info)
      printf '%s' '{"data":{"installed":true}}'
      ;;
    *)
      return 1
      ;;
  esac
}

supervisor_post() {
  endpoint=$1
  payload=$2
  case "$endpoint:$payload" in
    /addons/local_demo/options:'{"auto_update":false}'|/addons/webapp_updater/options:'{"auto_update":false}')
      auto_update_calls=$((auto_update_calls + 1))
      ;;
    *)
      return 1
      ;;
  esac
}

create_pre_update_backup "local_demo" "Demo-App" "1.2.3" "1.2.4"
jq -e '
  length == 1
  and .[0].addon == "local_demo"
  and .[0].from_version == "1.2.3"
  and .[0].to_version == "1.2.4"
  and .[0].backup_slug == "backup_demo_001"
  and (tostring | contains("password") | not)
' "$UPDATE_BACKUP_INDEX" >/dev/null
[ -s "$UPDATE_BACKUP_PASSWORD_FILE" ]
[ "$post_calls" -eq 1 ]

# A retry for the same version pair must reuse the verified checkpoint rather
# than creating another backup.
create_pre_update_backup "local_demo" "Demo-App" "1.2.3" "1.2.4"
[ "$post_calls" -eq 1 ]

# Native Home Assistant auto-updates must be disabled once and only be checked
# again when the managed-app list changes.
enforce_native_auto_update_policy
[ "$auto_update_calls" -eq 2 ]
enforce_native_auto_update_policy
[ "$auto_update_calls" -eq 2 ]

# Persisted update metadata must survive a restart so the new updater instance
# can confirm and report a self-update after its container was replaced.
PENDING_UPDATE_STATE_DIR="$test_dir/pending-update-state"
remember_pending_update "local_demo" "Demo-App" "1.2.3" "1.2.4"
saved_state=$(pending_update_state "local_demo")
printf '%s' "$saved_state" | jq -e '
  .local_slug == "local_demo"
  and .app_name == "Demo-App"
  and .from_version == "1.2.3"
  and .to_version == "1.2.4"
' >/dev/null
clear_pending_update_state "local_demo"
[ ! -e "$PENDING_UPDATE_STATE_DIR/local_demo.json" ]

# A Supervisor background job is only successful once the installed app
# version has actually reached the requested target.
version_counter="$test_dir/version-counter"
printf '0' > "$version_counter"
supervisor_get() {
  case "$1" in
    /addons/local_demo/info)
      count=$(cat "$version_counter")
      count=$((count + 1))
      printf '%s' "$count" > "$version_counter"
      if [ "$count" -ge 2 ]; then
        printf '%s' '{"data":{"version":"1.2.4"}}'
      else
        printf '%s' '{"data":{"version":"1.2.3"}}'
      fi
      ;;
    /jobs/job_demo)
      printf '%s' '{"data":{"done":true,"errors":[]}}'
      ;;
    *)
      return 1
      ;;
  esac
}
wait_for_supervisor_job "job_demo" "local_demo" "1.2.4" 0

# A finished Supervisor job with errors must not be marked as installed.
printf '0' > "$version_counter"
supervisor_get() {
  case "$1" in
    /addons/local_demo/info)
      printf '%s' '{"data":{"version":"1.2.3"}}'
      ;;
    /jobs/job_error)
      printf '%s' '{"data":{"done":true,"errors":[{"message":"build failed"}]}}'
      ;;
    *)
      return 1
      ;;
  esac
}
! wait_for_supervisor_job "job_error" "local_demo" "1.2.4" 0

printf '%s\n' 'test_pre_update_backup: ok'