"""Acesso anônimo ao bucket público de dados abertos do ONS (S3, us-west-2)."""
import re
import xml.etree.ElementTree as ET
from typing import Iterable, Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
_YEAR_RE = re.compile(r"(20\d{2})")


def make_session() -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    sess.mount("https://", HTTPAdapter(max_retries=retry))
    sess.headers["User-Agent"] = "ons-dashboard-ingestor/1.0"
    return sess


def list_objects(base_url: str, prefix: str, sess: requests.Session) -> Iterator[dict]:
    """Lista objetos sob `prefix` via ListObjectsV2 (com paginação)."""
    token = None
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if token:
            params["continuation-token"] = token
        resp = sess.get(base_url, params=params, timeout=60)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for c in root.findall("s3:Contents", _NS):
            yield {
                "key": c.findtext("s3:Key", namespaces=_NS),
                "etag": (c.findtext("s3:ETag", namespaces=_NS) or "").strip('"'),
                "size": int(c.findtext("s3:Size", namespaces=_NS) or 0),
            }
        if root.findtext("s3:IsTruncated", namespaces=_NS) == "true":
            token = root.findtext("s3:NextContinuationToken", namespaces=_NS)
        else:
            break


def year_of(key: str) -> int | None:
    name = key.rsplit("/", 1)[-1]
    m = _YEAR_RE.search(name)
    return int(m.group(1)) if m else None


def select_keys(objects: Iterable[dict], min_year: int) -> list[dict]:
    """Mantém só .parquet (preferencial) ou .csv cujo ano no nome do arquivo seja >= min_year."""
    by_stem: dict[str, dict] = {}
    for obj in objects:
        key = obj["key"]
        lower = key.lower()
        if not lower.endswith((".parquet", ".csv")):
            continue
        year = year_of(key)
        if year is None or year < min_year:
            continue
        stem = key.rsplit(".", 1)[0]
        if stem not in by_stem or lower.endswith(".parquet"):
            by_stem[stem] = obj
    return sorted(by_stem.values(), key=lambda o: o["key"])


def download(base_url: str, key: str, sess: requests.Session) -> bytes:
    resp = sess.get(f"{base_url}/{key}", timeout=300)
    resp.raise_for_status()
    return resp.content
