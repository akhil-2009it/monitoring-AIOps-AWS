"""EKS audit log + control plane log parser. Both are JSON."""
from __future__ import annotations
import json
from . import make_event


_AUDIT_VERB_TO_SEVERITY = {
    "delete":  "WARN",
    "deletecollection": "WARN",
    "patch":   "INFO",
    "update":  "INFO",
    "create":  "INFO",
    "get":     "DEBUG",
    "list":    "DEBUG",
    "watch":   "DEBUG",
}


def parse_eks(line: str | dict) -> dict | None:
    rec = json.loads(line) if isinstance(line, str) else line
    if not rec:
        return None

    # K8s audit format
    if rec.get("kind") == "Event" and "verb" in rec:
        verb = rec.get("verb", "")
        user = (rec.get("user") or {}).get("username", "")
        obj  = rec.get("objectRef") or {}
        return make_event(
            source="eks",
            ts=rec.get("requestReceivedTimestamp", rec.get("stageTimestamp", "")),
            host=rec.get("auditID", ""),
            severity=_AUDIT_VERB_TO_SEVERITY.get(verb, "INFO"),
            user=user,
            src_ip=(rec.get("sourceIPs") or [None])[0],
            path=f"{obj.get('apiGroup','')}/{obj.get('resource','')}/{obj.get('name','')}".strip("/"),
            message=f"{verb} {obj.get('resource', '')} by {user}",
            attrs={
                "verb":              verb,
                "stage":             rec.get("stage"),
                "response_status":   (rec.get("responseStatus") or {}).get("code"),
                "namespace":         obj.get("namespace"),
                "resource":          obj.get("resource"),
                "request_uri":       rec.get("requestURI"),
            },
        )

    # Control plane log line
    return make_event(
        source="eks",
        ts=rec.get("ts", rec.get("timestamp", "")),
        host=rec.get("hostname"),
        severity=str(rec.get("level", "INFO")).upper(),
        message=rec.get("msg", rec.get("message", "")),
        attrs=rec,
    )
