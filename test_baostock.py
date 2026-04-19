import subprocess
import sys

def test_baostock():
    try:
        import baostock as bs
        print("baostock is installed!")
    except ImportError:
        print("baostock is not installed.")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "baostock"])
        print("Installed baostock.")

test_baostock()
