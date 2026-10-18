"""Fetches reference results from the BMF's official Lohnsteuer interface.

The BMF "externe Schnittstelle" exists for quality assurance of third-party
implementations ("nur für die Überprüfung ihrer Rechnung bestimmt"). We use it
once to create backend/tests/golden/bmf_reference_vectors.json; the test suite
then runs fully offline.

Usage: python3 tools/bmf_reference/fetch.py [sample_size]
"""

import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.pap.interpreter import load_pap  # noqa: E402

ACCESS_CODE = "LSt2026ext"  # public QA access code of bmf-steuerrechner.de


def query_bmf(year: int, inputs: dict) -> dict:
    params = dict(inputs, code=ACCESS_CODE, KVZ=f"{inputs['KVZ']:.2f}")
    url = f"https://www.bmf-steuerrechner.de/interface/{year}Version1.xhtml?" + urllib.parse.urlencode(params)
    body = urllib.request.urlopen(url, timeout=20).read().decode()
    found = re.findall(r'name="(LSTLZZ|SOLZLZZ|BK)" value="(-?\d+)"', body)
    if len(found) != 3:
        raise RuntimeError(f"unexpected BMF response: {body[:300]}")
    return {k: int(v) for k, v in found}


def main() -> None:
    sample_size = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    official = json.loads((ROOT / "backend/tests/golden/official_vectors.json").read_text())
    rng = random.Random(42)
    vectors = []
    for v in official["pap"]:
        i = dict(v["input"])
        factor = i.pop("F")
        i["af"] = i.pop("AF")
        i["f"] = factor if i["af"] else 1.0
        pap = load_pap(v["year"])
        vectors.append((v["year"], {k: x for k, x in i.items() if k in pap.inputs}, v["output"]))

    # every case where the official TS and our engine disagree + a random sample
    disputed = [x for x in vectors if load_pap(x[0]).run(**x[1]) != {**load_pap(x[0]).run(**x[1]), **x[2]}]
    chosen = disputed + rng.sample([x for x in vectors if x not in disputed], sample_size)

    out = []
    for year, inputs, official_out in chosen:
        out.append({"year": year, "input": inputs, "bmf": query_bmf(year, inputs), "official_ts": official_out})
        time.sleep(0.3)  # be gentle with the public service
    target = ROOT / "backend/tests/golden/bmf_reference_vectors.json"
    target.write_text(json.dumps({"source": "https://www.bmf-steuerrechner.de (externe Schnittstelle)", "vectors": out}))
    print(f"wrote {len(out)} BMF reference vectors ({len(disputed)} disputed) to {target}")


if __name__ == "__main__":
    main()
