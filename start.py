import subprocess
import os
import sys

os.environ['PYTHONPATH'] = '/root/quant-sandbox'

cmd = [
    sys.executable, 
    '-m', 
    'uvicorn', 
    'src.quant_sandbox.api.server:app',
    '--host', '0.0.0.0',
    '--port', '8000'
]

subprocess.Popen(
    cmd,
    cwd='/root/quant-sandbox',
    env={**os.environ, 'PYTHONPATH': '/root/quant-sandbox'},
    stdout=open('/root/quant-sandbox/server.log', 'a'),
    stderr=subprocess.STDOUT
)
print('Server started')
