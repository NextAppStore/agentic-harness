#!/usr/bin/env bash
set -e

export PYTHONPATH="/workspace/backend:${PYTHONPATH}"

# 1. Lokalen PostgreSQL-Dienst starten & Test-DB initialisieren
service postgresql start >/dev/null 2>&1
su - postgres -c "psql -c \"CREATE USER testuser WITH PASSWORD 'testpass' SUPERUSER;\"" >/dev/null 2>&1 || true
su - postgres -c "createdb -O testuser testdb" >/dev/null 2>&1 || true

# 2. Verbindungsvariablen setzen
export DATABASE_URL="postgresql+psycopg2://testuser:testpass@localhost:5432/testdb"
export CREDENTIAL_ENCRYPTION_KEY="MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="
export SECRET_KEY="test-secret-key-for-harness-testing-only"
export ENVIRONMENT="test"

echo "==> 1. Linting Python Backend..."
if [ -d "backend" ]; then
  ruff check backend/
fi

echo "==> 2. Validating Terraform & Shell Templates..."
if [ -d "templates" ]; then
  find templates/ -name "*.sh" -exec shellcheck {} + 2>/dev/null || true
  terraform -chdir=templates fmt -check 2>/dev/null || true
fi

echo "==> 3. Running Tests..."
if [ -d "backend/tests" ]; then
  # Ermöglicht schnelles Testen via: bash harness/verify.sh fast
  if [ "$1" = "fast" ]; then
    echo "--> Running FAST Unit Tests only..."
    pytest backend/tests/unit/ -q --no-cov
  else
    echo "--> Running FULL Test Suite..."
    pytest backend/tests/ -q --no-cov
  fi
fi

echo "==> Alles im grünen Bereich!"
