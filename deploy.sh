#!/bin/bash
# MTU API Deploy Script
# Run from ~/mahakaal/

echo "=== MTU API Deploy ==="

# 1. Install deps
pip install -r ~/mahakaal/mtu_api/requirements.txt --break-system-packages

# 2. Create systemd service
sudo tee /etc/systemd/system/mtu-api.service > /dev/null << 'EOF'
[Unit]
Description=MTU Terminal FastAPI Backend
After=network.target

[Service]
User=balukasagatta1709
WorkingDirectory=/home/balukasagatta1709/mahakaal/mtu_api
ExecStart=/home/balukasagatta1709/mahakaal/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5
EnvironmentFile=/home/balukasagatta1709/mahakaal/env.vars

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable mtu-api
sudo systemctl restart mtu-api
sleep 3
sudo systemctl status mtu-api --no-pager | tail -8

echo ""
echo "=== Test API ==="
curl -s http://localhost:8000/api/health | python3 -m json.tool
