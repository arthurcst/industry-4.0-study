#!/bin/bash

# Cron não herda env_file do Docker — exportar vars para o cronjob_executor
printenv | grep -E '^(PG_|BATCH_|MQTT_|EXPERIMENT_)' | sort -u > /app/cron.env

# Inicia o cron em background
cron

mkdir -p /app/logs
touch /app/logs/batch_processor.log
tail -f /app/logs/batch_processor.log &

# Executa o consumer (unbuffered para aparecer em docker logs)
exec python -u batch_consumer.py