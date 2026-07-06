"""AWS WAF log parser. WAF emits JSON per request."""
from __future__ import annotations
import json
from . import make_event


def parse_waf(line: str | dict) -> dict | None:
    rec = json.loads(line) if isinstance(line, str) else line
    if not rec:
        return None

    http = rec.get("httpRequest", {})
    src_ip = http.get("clientIp")
    headers = {h["name"].lower(): h["value"] for h in http.get("headers", [])}

    # Map WAF action → severity
    action = rec.get("action") or rec.get("terminatingRuleId", "")
    severity = {
        "BLOCK":     "ERROR",
        "ALLOW":     None,
        "COUNT":     "WARN",
        "CHALLENGE": "WARN",
        "CAPTCHA":   "WARN",
    }.get(action, None)

    return make_event(
        source="waf",
        ts=rec.get("timestamp", ""),
        host=rec.get("webaclId", ""),
        severity=severity,
        src_ip=src_ip,
        user_agent=headers.get("user-agent"),
        path=http.get("uri"),
        message=f"{action} {http.get('httpMethod', '?')} {http.get('uri', '?')}",
        attrs={
            "action":              action,
            "terminating_rule":    rec.get("terminatingRuleId"),
            "rate_based_rule_list": rec.get("rateBasedRuleList"),
            "non_terminating_matching_rules": rec.get("nonTerminatingMatchingRules"),
            "country":             rec.get("httpRequest", {}).get("country"),
        },
    )
