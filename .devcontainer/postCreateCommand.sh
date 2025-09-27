#!/usr/bin/env bash
set -euo pipefail

# Zorg dat we in de repo-root staan (zoals in devcontainer.json verwacht)
cd /workspaces/fc2stl

# Installeer Python deps (project + dev) met uv; maakt .venv/
uv sync

# Pre-commit hooks installeren als je die gebruikt
if [ -f .pre-commit-config.yaml ]; then
  uv run pre-commit install --install-hooks || true
fi

echo "Devcontainer klaar. Voorbeeldrun:"
echo "  fc2stl barge2dave --doc examples/Barge.FCStd --out ./out --dave-out ./out/barge.dave.txt \\"
echo "    --resource-prefix 'res: Barge/geometry' --length 85 --width 24 --hull-label-hint Barge --cfd-draft 3.0"

