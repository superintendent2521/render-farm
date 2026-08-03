#!/bin/sh
set -eu
mkdir -p "${FARM_DATA_DIR:-/data}"
chown -R farm:farm "${FARM_DATA_DIR:-/data}"
exec gosu farm "$@"

