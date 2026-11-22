#!/bin/sh
set -eu
node /usr/local/lib/tivoo/wait-ha-mcp.mjs
exec qwenaudio gateway --lan
