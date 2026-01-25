#!/bin/bash
export PYTHONPATH=/root/quant-sandbox
cd /root/quant-sandbox
nohup ./venv/bin/uvicorn src.quant_sandbox.api.server:app --host 0.0.0.0 --port 8000 >> server.log 2>&1 &
echo $!
