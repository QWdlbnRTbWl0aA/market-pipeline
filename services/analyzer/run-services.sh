#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m analyzer.services "$@"
