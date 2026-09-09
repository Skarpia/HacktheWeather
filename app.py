"""
app.py

Convenience entry point for the FlowSafe hackathon MVP.

The primary interface is the Streamlit dashboard. Run:

    streamlit run dashboard/streamlit_app.py

This file just re-exports the dashboard module so `streamlit run app.py`
also works, and gives a single obvious file to point judges at.
"""

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).parent / "dashboard" / "streamlit_app.py"), run_name="__main__")
