#!/bin/bash
apt-get update && apt-get install -y ffmpeg
pip install requirements.txt
python3 app.py
