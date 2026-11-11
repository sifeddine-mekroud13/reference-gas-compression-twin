#!/bin/sh
# Apply the container's nftables ruleset (needs CAP_NET_ADMIN), then drop to the app user.
set -e
nft -f "$1"
shift
export HOME=/home/app USER=app
exec setpriv --reuid=10001 --regid=10001 --clear-groups "$@"
