#!/bin/bash
while true; do
    /home/ubuntu/miniconda3/bin/python /home/ubuntu/signal_daily_scanner.py
    echo "=== 재시작 ==="
    sleep 10
done
