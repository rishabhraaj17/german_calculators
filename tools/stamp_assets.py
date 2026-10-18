"""Stamps the asset URLs in public/index.html with a hash of app.js and styles.css.

Browsers then load new JavaScript/CSS as soon as the page changes, instead of mixing a cached old
page with a new API. Run after editing public/static/: python3 tools/stamp_assets.py
(backend/tests/test_api.py fails while the stamp is out of date).
"""

import hashlib
import re
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "public"


def stamp() -> str:
    data = b"".join((PUBLIC / "static" / f).read_bytes() for f in ("app.js", "styles.css"))
    return hashlib.sha256(data).hexdigest()[:10]


def main() -> None:
    index = PUBLIC / "index.html"
    html = re.sub(r"(/static/(?:app\.js|styles\.css))(\?v=[0-9a-f]+)?", rf"\1?v={stamp()}", index.read_text())
    index.write_text(html)
    print(f"index.html assets stamped ?v={stamp()}")


if __name__ == "__main__":
    main()
