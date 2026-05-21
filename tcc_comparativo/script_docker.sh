#!/bin/bash

# Inicia o cron em background
cron

touch /app/logs/batch_processor.log
tail -f /app/logs/batch_processor.log &

# Executa seu script principal
python batch_consumer.py