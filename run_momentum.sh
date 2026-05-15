#!/bin/bash
while true; do
    /home/ubuntu/miniconda3/bin/python /home/ubuntu/signal_momentum_us.py
    echo "=== 급등스캐너 5분 대기 후 재실행 ==="
    sleep 300
done
