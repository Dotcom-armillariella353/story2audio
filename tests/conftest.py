import sys
import os

# Put the root directory into sys.path so tests can import modules like `main`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
