#!/bin/bash
# Run this script once on a fresh Ubuntu 22.04 t2.micro after SSH-ing in.
# Usage: bash setup.sh
set -e

echo "=== 1. System update ==="
sudo apt update && sudo apt upgrade -y

echo "=== 2. Install packages ==="
sudo apt install -y python3.11 python3.11-venv python3-pip nginx certbot python3-certbot-nginx git

echo "=== 3. Clone repo ==="
git clone https://github.com/rysco78/electricity-usage.git ~/electricity-usage
cd ~/electricity-usage

echo "=== 4. Python virtualenv ==="
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

echo "=== 5. Create .env ==="
cat > .env << 'EOF'
AUTH0_DOMAIN=dev-fcqfkmqhorjckwvg.us.auth0.com
AUTH0_CLIENT_ID=fSGVe5pSq13IS06QgQbCvSgTXyBNrjCS
DYNAMODB_TABLE=energy-plan-sessions
AWS_REGION=us-east-1
EOF

echo "=== 6. Install systemd service ==="
sudo cp deploy/electricity-usage.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable electricity-usage
sudo systemctl start electricity-usage

echo "=== 7. Configure nginx ==="
sudo cp deploy/nginx.conf /etc/nginx/sites-available/energy.ryanrscott.com
sudo ln -sf /etc/nginx/sites-available/energy.ryanrscott.com /etc/nginx/sites-enabled/energy.ryanrscott.com
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo ""
echo "=== DONE — one manual step left ==="
echo "Point energy.ryanrscott.com at this server's Elastic IP, wait for DNS,"
echo "then run: sudo certbot --nginx -d energy.ryanrscott.com"
echo ""
echo "App status: sudo systemctl status electricity-usage"
echo "App logs:   sudo journalctl -u electricity-usage -f"
