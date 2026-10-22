#!/usr/bin/env bash
# BastaCount AI - Launch Script
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "[!] Virtual environment not found. Creating venv..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

echo "========================================================"
echo "   BastaCount AI (বস্তা কাউন্টার) Server Starting...   "
echo "   Dashboard URL: http://localhost:8000                 "
echo "========================================================"

uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
