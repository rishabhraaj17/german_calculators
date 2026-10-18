#!/usr/bin/env sh
# Regenerates backend/tests/golden/official_vectors.json from the official
# Elterngeldrechner source. Usage: tools/golden/run.sh /path/to/elterngeldrechner-clone
#   git clone https://gitlab.opencode.de/digitalservicebund/elterngeldrechner.git
set -eu
OFFICIAL="${1:?path to a clone of the official elterngeldrechner repository}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
COMMIT="$(git -C "$OFFICIAL" rev-parse HEAD)"

docker run --rm \
  -v "$OFFICIAL":/official \
  -v "$HERE":/harness:ro \
  -e OFFICIAL_COMMIT="$COMMIT" \
  -e TSX_TSCONFIG_PATH=/official/tsconfig.json \
  -w /official \
  node:24-alpine \
  sh -c 'set -e
    # Only the runtime libraries of the calculation modules are needed
    # (versions as pinned in the official package-lock.json).
    mkdir -p /tmp/deps && cd /tmp/deps && npm init -y >/dev/null
    npm install --ignore-scripts --no-audit --no-fund date-fns@4.4.0 @date-fns/utc@2.1.1 >/dev/null 2>&1
    rm -rf /official/node_modules && cp -r /tmp/deps/node_modules /official/node_modules
    cd /official && npx --yes tsx@4.19.2 /harness/generate.ts' \
  > "$ROOT/backend/tests/golden/official_vectors.json"

echo "wrote backend/tests/golden/official_vectors.json (official commit $COMMIT)"
