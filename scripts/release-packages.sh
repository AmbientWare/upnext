#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'USAGE'
Build and optionally publish UpNext packages.

Usage:
  scripts/release-packages.sh -r <target> [options]

Targets:
  all                    Build/publish in dependency order: shared -> server -> upnext
  shared|upnext-shared  Shared package only
  server|upnext-server  Server package only
  upnext     Main package only

Options:
  -r, --release <target>   Release target (required)
  -i, --index <name>       Publish index: pypi (default) or testpypi
  -t, --token <token>      PyPI token (defaults to UV_PUBLISH_TOKEN)
      --build-only         Build distributions but do not publish
      --publish-only       Publish existing dist artifacts without rebuilding
      --no-clean           Do not remove existing dist directories before build
      --dry-run            Print commands without executing them
  -h, --help               Show this help

Examples:
  scripts/release-packages.sh -r all
  scripts/release-packages.sh -r upnext --build-only
  scripts/release-packages.sh -r all -i testpypi --dry-run
USAGE
}

release_target=""
index_name="pypi"
publish_token="${UV_PUBLISH_TOKEN:-}"
do_build=1
do_publish=1
clean_dist=1
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--release)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 1; }
      release_target="$2"
      shift 2
      ;;
    -i|--index)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 1; }
      index_name="$2"
      shift 2
      ;;
    -t|--token)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 1; }
      publish_token="$2"
      shift 2
      ;;
    --build-only)
      do_publish=0
      shift
      ;;
    --publish-only)
      do_build=0
      shift
      ;;
    --no-clean)
      clean_dist=0
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$release_target" ]]; then
  echo "--release is required" >&2
  usage
  exit 1
fi

if [[ "$do_build" -eq 0 && "$do_publish" -eq 0 ]]; then
  echo "Nothing to do: both build and publish are disabled" >&2
  exit 1
fi

resolve_targets() {
  case "$release_target" in
    all)
      echo "shared server upnext"
      ;;
    shared|upnext-shared)
      echo "shared"
      ;;
    server|upnext-server)
      echo "server"
      ;;
    upnext)
      echo "upnext"
      ;;
    *)
      echo "Invalid release target: $release_target" >&2
      exit 1
      ;;
  esac
}

package_dir_for() {
  case "$1" in
    shared) echo "packages/shared" ;;
    server) echo "packages/server" ;;
    upnext) echo "packages/upnext" ;;
    *)
      echo "Unknown package key: $1" >&2
      exit 1
      ;;
  esac
}

dist_name_for() {
  case "$1" in
    shared) echo "upnext-shared" ;;
    server) echo "upnext-server" ;;
    upnext) echo "upnext" ;;
    *)
      echo "Unknown package key: $1" >&2
      exit 1
      ;;
  esac
}

run_cmd() {
  if [[ "$dry_run" -eq 1 ]]; then
    printf '[dry-run]'
    for arg in "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
    return 0
  fi
  "$@"
}

check_publish_files() {
  local package_dir="$1"
  shopt -s nullglob
  local files=("$package_dir"/dist/*)
  shopt -u nullglob
  if [[ ${#files[@]} -eq 0 ]]; then
    echo "No dist files found in $package_dir/dist. Build first or remove --publish-only." >&2
    exit 1
  fi
}

case "$index_name" in
  pypi)
    check_url="https://pypi.org/simple"
    publish_url=""
    ;;
  testpypi)
    check_url="https://test.pypi.org/simple"
    publish_url="https://test.pypi.org/legacy/"
    ;;
  *)
    echo "Invalid index: $index_name (expected pypi or testpypi)" >&2
    exit 1
    ;;
esac

read -r -a targets <<<"$(resolve_targets)"

echo "Release target: $release_target"
echo "Packages: ${targets[*]}"
echo "Mode: build=$do_build publish=$do_publish index=$index_name"

if [[ "$do_build" -eq 1 ]]; then
  for key in "${targets[@]}"; do
    package_dir="$(package_dir_for "$key")"
    dist_name="$(dist_name_for "$key")"

    if [[ "$clean_dist" -eq 1 ]]; then
      run_cmd rm -rf "$package_dir/dist"
    fi

    echo "Building $dist_name from $package_dir"
    run_cmd uv build "$package_dir" --out-dir "$package_dir/dist"
  done
fi

if [[ "$do_publish" -eq 1 ]]; then
  if [[ -z "$publish_token" ]]; then
    echo "Publishing requires a token. Set UV_PUBLISH_TOKEN or pass --token." >&2
    exit 1
  fi

  export UV_PUBLISH_TOKEN="$publish_token"

  for key in "${targets[@]}"; do
    package_dir="$(package_dir_for "$key")"
    dist_name="$(dist_name_for "$key")"

    if [[ "$dry_run" -eq 1 ]]; then
      files=("$package_dir/dist/*")
    else
      check_publish_files "$package_dir"
      shopt -s nullglob
      files=("$package_dir"/dist/*)
      shopt -u nullglob
    fi

    echo "Publishing $dist_name (${#files[@]} files)"
    if [[ -n "$publish_url" ]]; then
      run_cmd uv publish --check-url "$check_url" --publish-url "$publish_url" "${files[@]}"
    else
      run_cmd uv publish --check-url "$check_url" "${files[@]}"
    fi
  done
fi

echo "Done."
