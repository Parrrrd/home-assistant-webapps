#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT HUP INT TERM

make_repository() {
  target=$1

  mkdir -p "$target"
  cp -a "$repository_root/scripts" "$target/"
  cp -a "$repository_root/webapp_updater" "$target/"
  cp -a "$repository_root/managed-webapps.json" "$target/"
  cp -a "$repository_root/.github" "$target/"
  cd "$target"
  git init -q
  git config user.name test
  git config user.email test@example.invalid
  git add .
  git commit -qm baseline
}

prepare_candidate() {
  source_directory=$1
  version=$2
  image=${3:-ghcr.io/parrrrd/home-assistant-webapps/webapp-updater}
  candidate=$4

  mkdir -p "$candidate"
  cp -a "$source_directory/webapp_updater" "$candidate/"
  current_version=$(awk '/^version: / { print $2; exit }' "$candidate/webapp_updater/config.yaml")
  perl -0pi -e "s/version: \\Q${current_version}\\E/version: ${version}/" "$candidate/webapp_updater/config.yaml"
  perl -0pi -e "s/BUILD_VERSION=\\Q${current_version}\\E/BUILD_VERSION=${version}/" "$candidate/webapp_updater/Dockerfile"
  perl -0pi -e "s#image: ghcr.io/parrrrd/home-assistant-webapps/webapp-updater#image: ${image}#" "$candidate/webapp_updater/config.yaml"
  {
    printf '## %s — 25.09.2026, 12:00 CEST\n\n- Verhaltenstest.\n\n' "$version"
    cat "$candidate/webapp_updater/CHANGELOG.md"
  } > "$candidate/webapp_updater/CHANGELOG.md.new"
  mv "$candidate/webapp_updater/CHANGELOG.md.new" "$candidate/webapp_updater/CHANGELOG.md"
}

current_version=$(awk '/^version: / { print $2; exit }' "$repository_root/webapp_updater/config.yaml")
case "$current_version" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *)
    echo "Die WebApp-Updater-Version ist nicht semantisch." >&2
    exit 1
    ;;
esac
test_version=$(printf '%s\n' "$current_version" | awk -F. '{ printf "%d.%d.%d", $1, $2, $3 + 1 }')

# A correctly structured, higher updater ZIP is accepted and keeps the
# privileged updater path explicit rather than treating it as a bootstrap app.
zip_repository="$test_dir/zip-repository"
make_repository "$zip_repository"
zip_candidate="$test_dir/zip-candidate"
prepare_candidate "$zip_repository" "$test_version" '' "$zip_candidate"
(cd "$zip_candidate" && zip -qr "$test_dir/webapp_updater-${test_version}.zip" webapp_updater)
sh "$zip_repository/scripts/import-google-drive-package.sh" "$test_dir/webapp_updater-${test_version}.zip" "webapp_updater-${test_version}.zip"
grep -Fqx "version: $test_version" "$zip_repository/webapp_updater/config.yaml"

# The ZIP path must reject a wrong image even though the package name, version
# and folder are otherwise plausible.
bad_zip_repository="$test_dir/bad-zip-repository"
make_repository "$bad_zip_repository"
bad_zip_candidate="$test_dir/bad-zip-candidate"
prepare_candidate "$bad_zip_repository" "$test_version" ghcr.io/example/incorrect "$bad_zip_candidate"
(cd "$bad_zip_candidate" && zip -qr "$test_dir/webapp_updater-bad.zip" webapp_updater)
if sh "$bad_zip_repository/scripts/import-google-drive-package.sh" "$test_dir/webapp_updater-bad.zip" "webapp_updater-${test_version}.zip"; then
  echo 'Ungültiger WebApp-Updater-ZIP-Imagepfad wurde akzeptiert.' >&2
  exit 1
fi

# A full text patch for the existing updater is accepted, including the
# required version and changelog checks.
patch_repository="$test_dir/patch-repository"
make_repository "$patch_repository"
prepare_candidate "$patch_repository" "$test_version" '' "$test_dir/patch-candidate"
rm -rf "$patch_repository/webapp_updater"
cp -a "$test_dir/patch-candidate/webapp_updater" "$patch_repository/"
(cd "$patch_repository" && git diff -- webapp_updater > "$test_dir/webapp_updater-${test_version}.patch" && git restore webapp_updater)
sh "$patch_repository/scripts/import-google-drive-patch.sh" "$test_dir/webapp_updater-${test_version}.patch" "webapp_updater-${test_version}.patch"
grep -Fqx "version: $test_version" "$patch_repository/webapp_updater/config.yaml"

# A text patch cannot smuggle a symlink into the updater directory.
symlink_repository="$test_dir/symlink-repository"
make_repository "$symlink_repository"
cat > "$test_dir/webapp_updater-${test_version}.patch" <<'PATCH'
diff --git a/webapp_updater/forbidden-link b/webapp_updater/forbidden-link
new file mode 120000
index 0000000..3594e94
--- /dev/null
+++ b/webapp_updater/forbidden-link
@@ -0,0 +1 @@
+/etc/passwd
PATCH
if sh "$symlink_repository/scripts/import-google-drive-patch.sh" "$test_dir/webapp_updater-${test_version}.patch" "webapp_updater-${test_version}.patch"; then
  echo 'Symlink im WebApp-Updater-Patch wurde akzeptiert.' >&2
  exit 1
fi

printf '%s\n' 'test-google-drive-importers: ok'
