#!/usr/bin/env bash
# Teste de backup e restauracao do banco (Protocolo v3.1, secao 6/8).
#
# Faz pg_dump do banco de producao, restaura numa base de teste DENTRO do mesmo
# contentor, compara a contagem das tabelas que guardam o dataset e derruba a
# base de teste. Prova que o backup restaura, antes de gerar o conjunto.
#
# Pre-requisito: a stack de paga de pe (`docker compose up -d phishforge-postgresql`).
# Uso: bash script/testar_backup.sh
set -euo pipefail

CONTENTOR="${PG_CONTAINER:-phishforge-postgresql}"
DB="${DB_NAME:-phishforge}"
USER="${DB_USER:-phishforge}"
TESTDB="${DB}_backup_test"
CARIMBO="$(date +%Y%m%d_%H%M%S)"
DIR="${BACKUP_DIR:-backups}"
DUMP="${DIR}/${DB}_${CARIMBO}.dump"
TABELAS=(phishing_emails generation_jobs)

mkdir -p "$DIR"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTENTOR"; then
  echo "ERRO: contentor '$CONTENTOR' nao esta rodando. Suba a stack: docker compose up -d phishforge-postgresql" >&2
  exit 1
fi

echo "1. pg_dump de '$DB' -> $DUMP"
docker exec "$CONTENTOR" pg_dump -U "$USER" -F c -d "$DB" > "$DUMP"
echo "   tamanho: $(du -h "$DUMP" | cut -f1)"

echo "2. criando base de teste '$TESTDB'"
docker exec "$CONTENTOR" psql -U "$USER" -d "$DB" -c "DROP DATABASE IF EXISTS ${TESTDB};"
docker exec "$CONTENTOR" psql -U "$USER" -d "$DB" -c "CREATE DATABASE ${TESTDB};"

echo "3. restaurando o dump em '$TESTDB'"
docker exec -i "$CONTENTOR" pg_restore -U "$USER" -d "$TESTDB" --no-owner < "$DUMP"

echo "4. comparando contagens (original vs restaurado)"
ok=1
for t in "${TABELAS[@]}"; do
  a=$(docker exec "$CONTENTOR" psql -U "$USER" -d "$DB" -tAc "SELECT count(*) FROM ${t};" 2>/dev/null || echo "ERR")
  b=$(docker exec "$CONTENTOR" psql -U "$USER" -d "$TESTDB" -tAc "SELECT count(*) FROM ${t};" 2>/dev/null || echo "ERR")
  if [ "$a" = "$b" ] && [ "$a" != "ERR" ]; then
    echo "   OK  ${t}: ${a} = ${b}"
  else
    echo "   FALHA ${t}: original=${a} restaurado=${b}"
    ok=0
  fi
done

echo "5. derrubando a base de teste '$TESTDB'"
docker exec "$CONTENTOR" psql -U "$USER" -d "$DB" -c "DROP DATABASE IF EXISTS ${TESTDB};"

if [ "$ok" = 1 ]; then
  echo "RESULTADO: backup restaura com sucesso. Dump guardado em $DUMP"
  exit 0
else
  echo "RESULTADO: FALHA na restauracao -- NAO gere o conjunto ate resolver." >&2
  exit 1
fi
