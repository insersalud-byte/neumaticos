import sys
import os

# Add backend to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))

# Signal to main.py that we're running on Vercel (no filesystem, no static files)
os.environ.setdefault('VERCEL', '1')

from main import app
