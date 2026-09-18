#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERROR: falta .env"
  exit 1
fi

if [ ! -d venv ]; then
  python3 -m venv venv
fi
. venv/bin/activate
python -m pip install --disable-pip-version-check -r requirements.txt
python scripts/doctor.py
exec python app.py
