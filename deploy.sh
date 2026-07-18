#!/bin/bash
# ===========================================================================
# Tailwind AI — EC2 Deploy Script
# Run this on a fresh EC2 instance (Amazon Linux 2023 or Ubuntu 22+)
# ===========================================================================
set -e

echo "🚀 Deploying Tailwind AI..."

# ---------------------------------------------------------------------------
# 1. Install Python 3.11+ (AL2023 has 3.9, Ubuntu 22 has 3.10)
# ---------------------------------------------------------------------------
if command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
elif command -v python3.12 &>/dev/null; then
    PYTHON=python3.12
elif command -v python3.13 &>/dev/null; then
    PYTHON=python3.13
elif command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if [[ $(echo "$PY_VER >= 3.10" | bc -l 2>/dev/null || python3 -c "print(1 if tuple(map(int,'$PY_VER'.split('.'))) >= (3,10) else 0)") == "1" ]]; then
        PYTHON=python3
    else
        echo "⚠️  Python 3.10+ required. Installing..."
        if command -v dnf &>/dev/null; then
            sudo dnf install -y python3.11 python3.11-pip
            PYTHON=python3.11
        elif command -v apt-get &>/dev/null; then
            sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv python3-pip
            PYTHON=python3.11
        else
            echo "❌ Cannot install Python automatically. Install Python 3.10+ manually."
            exit 1
        fi
    fi
else
    echo "❌ No Python found. Installing..."
    if command -v dnf &>/dev/null; then
        sudo dnf install -y python3.11 python3.11-pip
        PYTHON=python3.11
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv python3-pip
        PYTHON=python3.11
    else
        echo "❌ Cannot install Python. Install Python 3.10+ manually."
        exit 1
    fi
fi

echo "✓ Using $PYTHON ($(${PYTHON} --version))"

# ---------------------------------------------------------------------------
# 2. Set up venv + install deps
# ---------------------------------------------------------------------------
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    ${PYTHON} -m venv .venv
fi
source .venv/bin/activate

echo "📦 Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# ---------------------------------------------------------------------------
# 3. Create .env if it doesn't exist
# ---------------------------------------------------------------------------
if [ ! -f ".env" ]; then
    echo "📝 Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANT: Edit .env with your credentials:"
    echo "   nano .env"
    echo ""
fi

# ---------------------------------------------------------------------------
# 4. Open firewall port 8787 (if iptables/firewalld is active)
# ---------------------------------------------------------------------------
if command -v firewall-cmd &>/dev/null; then
    sudo firewall-cmd --add-port=8787/tcp --permanent 2>/dev/null || true
    sudo firewall-cmd --reload 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# 5. Start the server
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "  ✈️  Tailwind AI"
echo "============================================"
echo ""

# Get public IP
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || curl -s ifconfig.me 2>/dev/null || echo "localhost")

echo "  Server:    http://${PUBLIC_IP}:8787"
echo "  Health:    http://${PUBLIC_IP}:8787/sabre/health"
echo "  API:       http://${PUBLIC_IP}:8787/api/flights/search"
echo ""
echo "  VB Tool Base URL: http://${PUBLIC_IP}:8787"
echo ""
echo "  Register these in Vocal Bridge dashboard:"
echo "    POST http://${PUBLIC_IP}:8787/api/flights/search"
echo "    POST http://${PUBLIC_IP}:8787/api/hotels/search"
echo "    POST http://${PUBLIC_IP}:8787/api/hotels/rates"
echo "    POST http://${PUBLIC_IP}:8787/api/price/check"
echo "    POST http://${PUBLIC_IP}:8787/api/book"
echo "    GET  http://${PUBLIC_IP}:8787/api/preferences"
echo ""
echo "============================================"
echo "  Starting server on 0.0.0.0:8787..."
echo "============================================"
echo ""

exec uvicorn main:app --host 0.0.0.0 --port 8787
