"""
Start both the FastAPI backend and Streamlit frontend.

Usage:
    python run.py

The FastAPI server runs on port 8000.
The Streamlit app runs on port 8501.

Press Ctrl+C to stop both.
"""

import subprocess
import sys
import os
import signal
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)


def main():
    print("=" * 60)
    print("  Schema Drift Impact Analyzer")
    print("  Starting FastAPI + Streamlit...")
    print("=" * 60)

    # Start FastAPI
    api_process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "api.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload",
        ],
        cwd=PROJECT_ROOT,
    )

    # Give FastAPI a moment to start
    time.sleep(2)

    # Start Streamlit
    ui_process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit",
            "run", "app.py",
            "--server.port", "8501",
            "--server.headless", "true",
        ],
        cwd=PROJECT_ROOT,
    )

    print()
    print("  FastAPI docs : http://localhost:8000/docs")
    print("  Streamlit UI : http://localhost:8501")
    print()
    print("  Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        api_process.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        api_process.terminate()
        ui_process.terminate()
        api_process.wait()
        ui_process.wait()
        print("Done.")


if __name__ == "__main__":
    main()
