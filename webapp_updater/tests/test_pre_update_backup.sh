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

# Backup details expose apps as objects, while overview responses expose
# content.addons as strings. Both forms must verify the requested app.
backup_contains_addon "local_demo" '{"data":{"addons":[{"slug":"local_demo"}]}}'
backup_contains_addon "local_demo" '{"data":{"content":{"addons":["local_demo"]}}}'
! backup_contains_addon "local_demo" '{"data":{"addons":[{"slug":"local_other"}]}}'

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
      printf '%s' '{"data":{"addons":[{"slug":"local_demo","name":"Demo-App","version":"1.2.3","size":1}]}}'
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

# The current Supervisor API returns a job object directly from /jobs/<uuid>
# and running jobs from /jobs/info. Monitoring is one non-blocking cycle: it
# persists stage and progress and never sends a second update request.
PENDING_UPDATES="$test_dir/pending-updates"
PENDING_UPDATE_STATE_DIR="$test_dir/pending-update-state"
HISTORY_FILE="$test_dir/history"
start_calls=0
job_mode=running
installed_version=1.2.3
latest_version=1.2.4

supervisor_start_update() {
  start_calls=$((start_calls + 1))
  SUPERVISOR_UPDATE_JOB_ID="job_started"
  SUPERVISOR_UPDATE_STATUS=200
  SUPERVISOR_UPDATE_DETAIL=''
}

ensure_addon_started() { return 0; }
send_iphone_notification() { :; }
create_pre_update_backup() { return 0; }

supervisor_get() {
  case "$1" in
    /addons/local_demo/info)
      printf '{"data":{"installed":true,"name":"Demo-App","version":"%s","version_latest":"%s"}}' "$installed_version" "$latest_version"
      ;;
    /jobs/info)
      if [ "$job_mode" = discovered ]; then
        printf '%s' '{"jobs":[{"uuid":"job_existing","reference":"local_demo","stage":"build","progress":42,"done":false,"errors":[]}]}'
      else
        printf '%s' '{"jobs":[]}'
      fi
      ;;
    /jobs/job_running)
      printf '%s' '{"uuid":"job_running","stage":"build","progress":42,"done":false,"errors":[]}'
      ;;
    /jobs/job_error)
      printf '%s' '{"uuid":"job_error","stage":"install","progress":83,"done":true,"errors":[{"message":"build failed","stage":"install"}]}'
      ;;
    *)
      return 1
      ;;
  esac
}

printf '%s\n' local_demo > "$PENDING_UPDATES"
remember_pending_update local_demo Demo-App 1.2.3 1.2.4
update_pending_job_state local_demo job_running running queued '' ''
if process_pending_update local_demo; then
  process_result=0
else
  process_result=$?
fi
[ "$process_result" -eq 10 ]
[ "$start_calls" -eq 0 ]
pending_update_state local_demo | jq -e '
  .job_id == "job_running" and .job_status == "running"
  and .job_stage == "build" and .job_progress == 42
' >/dev/null

# A terminal job error is recorded and remains queued; retrying it blindly
# would risk a second update job for the same app.
update_pending_job_state local_demo job_error running queued '' ''
job_mode=error
process_pending_update local_demo
pending_update_state local_demo | jq -e '
  .job_status == "failed" and .job_stage == "install"
  and (.last_error | contains("build failed"))
' >/dev/null
[ "$start_calls" -eq 0 ]

# A restart resumes the saved job state. Once the installed target is observed,
# only then are queue, persistent state and history completed.
installed_version=1.2.4
process_pending_update local_demo
[ ! -e "$PENDING_UPDATE_STATE_DIR/local_demo.json" ]
! grep -Fqx local_demo "$PENDING_UPDATES"
grep -Fq 'Demo-App | 1.2.3 → 1.2.4 | installiert' "$HISTORY_FILE"

# Before starting a new request, a live job for the same add-on is discovered
# via /jobs/info and adopted rather than duplicated.
installed_version=1.2.3
job_mode=discovered
printf '%s\n' local_demo > "$PENDING_UPDATES"
remember_pending_update local_demo Demo-App 1.2.3 1.2.4
if process_pending_update local_demo; then
  process_result=0
else
  process_result=$?
fi
[ "$process_result" -eq 10 ]
[ "$start_calls" -eq 0 ]
pending_update_state local_demo | jq -e '
  .job_id == "job_existing" and .job_status == "running"
  and .job_stage == "discovered"
' >/dev/null

# With no existing job, the request returns immediately after persisting the
# returned job ID. There is no 600-second in-process wait.
clear_pending_update_state local_demo
job_mode=none
if process_pending_update local_demo; then
  process_result=0
else
  process_result=$?
fi
[ "$process_result" -eq 11 ]
[ "$start_calls" -eq 1 ]
pending_update_state local_demo | jq -e '
  .job_id == "job_started" and .job_status == "running"
  and .job_stage == "started"
' >/dev/null

# A job missing from both Supervisor endpoints is not retried immediately. If
# it is still absent in the next cycle and the target version is unchanged,
# the already verified backup allows exactly one safely re-submitted job.
update_pending_job_state local_demo job_missing running queued '' ''
if process_pending_update local_demo; then
  process_result=0
else
  process_result=$?
fi
[ "$process_result" -eq 10 ]
pending_update_state local_demo | jq -e '
  .job_id == "job_missing" and .job_status == "job-unavailable"
' >/dev/null
if process_pending_update local_demo; then
  process_result=0
else
  process_result=$?
fi
[ "$process_result" -eq 11 ]
[ "$start_calls" -eq 2 ]

# A foreground Store update may return no job ID. It is only considered done
# after the target version is immediately observed; no pending state is left
# behind and no duplicate request is made.
clear_pending_update_state local_demo
printf '%s\n' local_demo > "$PENDING_UPDATES"
installed_version=1.2.3
supervisor_start_update() {
  start_calls=$((start_calls + 1))
  installed_version=1.2.4
  SUPERVISOR_UPDATE_JOB_ID=''
  SUPERVISOR_UPDATE_STATUS=200
  SUPERVISOR_UPDATE_DETAIL=''
}
process_pending_update local_demo
[ "$start_calls" -eq 3 ]
[ ! -e "$PENDING_UPDATE_STATE_DIR/local_demo.json" ]
! grep -Fqx local_demo "$PENDING_UPDATES"

printf '%s\n' 'test_pre_update_backup: ok'
