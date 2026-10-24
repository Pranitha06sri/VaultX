"""Generate fictional PDF receipts for local demonstration; never uses real data."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.samples import SAMPLES, sample_pdf

output = ROOT / "samples"
output.mkdir(exist_ok=True)
for sample in SAMPLES:
    destination = output / sample["name"]
    destination.write_bytes(sample_pdf(sample["name"]))
    print(f"Generated SYNTHETIC sample: {destination.name}")
