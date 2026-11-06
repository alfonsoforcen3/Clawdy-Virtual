#!/bin/bash
# Build the private prototype using Apple's installed Command Line Tools.
set -euo pipefail

source_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$source_dir/../.." && pwd)"
# Desktop may be managed by a cloud file provider that adds Finder metadata to
# .app bundles during signing. Keep executable artifacts in a local cache.
build_dir="${CLAWDY_BUILD_DIR:-$HOME/Library/Caches/ClawdyPrototype/Build}"
bundle="$build_dir/VirtualClawdy.app"
architecture="$(uname -m)"
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'The native prototype requires macOS.' >&2
  exit 1
fi
if [[ "$architecture" != arm64 && "$architecture" != x86_64 ]]; then
  echo "Unsupported build architecture: $architecture" >&2
  exit 1
fi

mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
compiler=(xcrun swiftc -parse-as-library -swift-version 5 -O
  -target "$architecture-apple-macosx13.0" -framework AppKit -framework QuartzCore)
"${compiler[@]}" "$source_dir/Shared.swift" "$source_dir/AttentionPanel.swift" "$source_dir/ClawdyHost.swift" \
  -o "$bundle/Contents/MacOS/VirtualClawdy"
"${compiler[@]}" "$source_dir/Shared.swift" "$source_dir/ClawdyRenderer.swift" \
  -o "$bundle/Contents/MacOS/ClawdyRenderer"
cp -X "$repo_dir/scripts/local_chat_routes.py" "$bundle/Contents/Resources/local_chat_routes.py"
cp -X "$repo_dir/scripts/virtual_clawdy.py" "$bundle/Contents/Resources/virtual_clawdy.py"
if [[ -f "$repo_dir/scripts/status_core.py" ]]; then
  cp -X "$repo_dir/scripts/status_core.py" "$bundle/Contents/Resources/status_core.py"
fi
cp -X "$source_dir/Assets/ClawdyProduct.png" "$bundle/Contents/Resources/ClawdyProduct.png"
cp -X "$source_dir/Info.plist" "$bundle/Contents/Info.plist"
# Finder metadata from cloud-backed source copies is not allowed in signatures.
# Strip only these build-artifact attributes; preserve quarantine/security flags.
xattr -dr com.apple.FinderInfo "$bundle" 2>/dev/null || true
xattr -dr com.apple.ResourceFork "$bundle" 2>/dev/null || true
codesign --force --sign - "$bundle/Contents/MacOS/ClawdyRenderer"
codesign --force --sign - "$bundle"
codesign --verify --deep --strict "$bundle"
echo "Private local build: $bundle"
echo 'Ad-hoc signed only; not a notarized customer installer.'
