#!/usr/bin/env python3
import paramiko
import time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('72.60.4.111', username='root', password='TOMASagustina01@')

channel = client.invoke_shell()

channel.send('pip3 install --break-system-packages reportlab\n')
time.sleep(30)

channel.send('cd /var/www/neumaticos/backend && nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &\n')
time.sleep(5)

channel.send('pgrep -f uvicorn && echo "RUNNING" || (cat /tmp/uvicorn.log | tail -10 && echo "FAILED")\n')
time.sleep(3)

output = ''
while channel.recv_ready():
    output += channel.recv(4096).decode('utf-8', errors='ignore')

with open('vps_output.txt', 'w', encoding='utf-8', errors='ignore') as f:
    f.write(output)

channel.close()
client.close()
print("Done")
