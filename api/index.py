import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from repo root
load_dotenv(Path(__file__).parent.parent / '.env')

# Add backend to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))

# Signal to main.py that we're running on Vercel (no filesystem, no static files)
os.environ.setdefault('VERCEL', '1')

from main import app
