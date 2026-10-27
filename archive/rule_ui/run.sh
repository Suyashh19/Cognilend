#!/usr/bin/env bash
# Start the rule-layer demo page at http://127.0.0.1:5000
cd "$(dirname "$0")"
exec .venv/bin/python app.py
