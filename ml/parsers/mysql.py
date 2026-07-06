"""MySQL slow-query log parser.
Each entry spans multiple lines; pass the full block as `block`.
"""
from __future__ import annotations
import re
from . import make_event

_TS = re.compile(r"# Time: (?P<ts>\S+)")
_USER = re.compile(r"# User@Host: (?P<user>\S+?)\[\S*?\] @ \S* \[(?P<ip>\S*)\]")
_QC = re.compile(r"# Query_time: (?P<qt>[\d.]+)\s+Lock_time: (?P<lt>[\d.]+)")
_QUERY = re.compile(r"^(?:SET timestamp.*?;\s*)?(?P<sql>.+);\s*$", re.MULTILINE | re.DOTALL)


def parse_mysql(block: str) -> dict | None:
    if "# Time:" not in block:
        return None
    ts = (m.group("ts") if (m := _TS.search(block)) else "")
    uh = _USER.search(block)
    qc = _QC.search(block)
    q  = _QUERY.search(block)

    qt = float(qc.group("qt")) if qc else None
    return make_event(
        source="mysql",
        ts=ts,
        severity="WARN" if (qt or 0) > 1.0 else "INFO",
        latency_ms=qt * 1000 if qt is not None else None,
        src_ip=uh.group("ip") if uh else None,
        user=uh.group("user") if uh else None,
        message=(q.group("sql").strip() if q else block.strip())[:4000],
        attrs={
            "lock_time": float(qc.group("lt")) if qc else None,
        },
    )
