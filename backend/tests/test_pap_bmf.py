"""The PAP interpreter reproduces the BMF's own Lohnsteuer calculator exactly.

bmf_reference_vectors.json was fetched from the BMF's quality-assurance
interface (tools/bmf_reference/fetch.py): every case where the official
BMFSFJ TypeScript port disagrees with this engine, plus a random sample.
"""

import json
from pathlib import Path

from app.pap.interpreter import load_pap

BMF = json.loads((Path(__file__).parent / "golden" / "bmf_reference_vectors.json").read_text())["vectors"]


def test_interpreter_equals_bmf_reference_calculator():
    assert len(BMF) >= 300
    for v in BMF:
        out = load_pap(v["year"]).run(**v["input"])
        assert {k: out[k] for k in v["bmf"]} == v["bmf"], v


def test_known_official_port_deviations_are_settled_by_bmf():
    disputed = [v for v in BMF if v["official_ts"] != v["bmf"]]
    assert len(disputed) >= 100  # all of them confirm this engine (previous test)
