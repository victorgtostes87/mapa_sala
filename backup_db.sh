#!/bin/bash
# backup_db.sh — Copia o banco de dados para a pasta de backups
# Mantém apenas os últimos 15 arquivos (15 dias)

ORIGEM="/home/victroid/mapa_sala/mapa_salas.db"
DESTINO="/home/victroid/backups"
ARQUIVO="mapa_$(date +%Y%m%d_%H%M).db"

# Cria a pasta de backups se não existir
mkdir -p "$DESTINO"

# Copia o banco
cp "$ORIGEM" "$DESTINO/$ARQUIVO"

# Remove backups mais antigos, mantendo só os últimos 15
cd "$DESTINO"
ls -t mapa_*.db | tail -n +16 | xargs -r rm --

echo "[$(date '+%Y-%m-%d %H:%M')] Backup criado: $DESTINO/$ARQUIVO"
