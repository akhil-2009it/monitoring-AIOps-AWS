"""Demo-app traffic generator.

Two modes (env var DEMO_MODE):

  normal  — realistic e-commerce browsing pattern. Most users browse,
            some add to cart, fewer check out, occasional login.

  attack  — simulate adversarial traffic patterns. Used to validate that
            the AIOps detectors fire. Sub-pattern via DEMO_ATTACK env var:
              ddos        — high-rate hits from many src IPs (need many
                            workers; locust spawns one user = one IP-ish).
              brute-force — hammer /login with bad credentials from a small
                            IP set, against a victim username pool.
              slow-loris  — long, slow requests holding open connections.
              sqli        — paths with SQL-injection patterns. Should be
                            blocked by WAF.

Run:
    locust -f locustfile.py --host https://demo.example.com \\
        --users 50 --spawn-rate 5 --run-time 30m --headless

Environment overrides:
    DEMO_MODE=normal|attack
    DEMO_ATTACK=ddos|brute-force|slow-loris|sqli
"""
from __future__ import annotations

import json
import os
import random
import time
import uuid
from urllib.parse import urlencode

from locust import HttpUser, between, events, task


MODE          = os.getenv("DEMO_MODE", "normal").lower()
ATTACK        = os.getenv("DEMO_ATTACK", "ddos").lower()
USERNAMES     = ["alice", "bob", "carol", "dave", "eve"]
SQLI_PAYLOADS = ["' OR 1=1--", "1; DROP TABLE users--", "%27%20UNION%20SELECT", "<script>alert(1)</script>"]


# ─── Normal user ─────────────────────────────────────────────────────────────

class NormalUser(HttpUser):
    """Browses, occasionally logs in, sometimes places an order."""

    wait_time = between(2, 8)
    user_id   = None

    def on_start(self):
        # ~30% of users log in at session start
        if random.random() < 0.3:
            uname = random.choice(USERNAMES)
            with self.client.post("/api/login",
                                    json={"username": uname, "password": "password123"},
                                    catch_response=True, name="/api/login") as r:
                if r.ok:
                    self.user_id = r.json().get("user_id")

    @task(10)
    def browse_home(self):
        self.client.get("/", name="/")

    @task(8)
    def browse_products(self):
        self.client.get("/api/products", name="/api/products")

    @task(4)
    def view_product(self):
        pid = random.randint(1, 8)
        self.client.get(f"/api/products/{pid}", name="/api/products/{id}")

    @task(2)
    def view_stats(self):
        self.client.get("/api/stats", name="/api/stats")

    @task(1)
    def place_order(self):
        if self.user_id is None:
            self.user_id = random.randint(1, 5)
        n = random.randint(1, 3)
        items = [{"product_id": random.randint(1, 8), "quantity": random.randint(1, 2)}
                 for _ in range(n)]
        self.client.post("/api/orders",
                          json={"user_id": self.user_id, "items": items, "payment_method": "card"},
                          name="/api/orders")


# ─── Attack patterns ────────────────────────────────────────────────────────

class DDosUser(HttpUser):
    """Burst of high-rate, low-latency requests from rotating fake IPs."""
    wait_time = between(0, 0.05)

    @task
    def hit(self):
        fake_ip = f"203.0.{random.randint(0, 254)}.{random.randint(0, 254)}"
        self.client.get("/api/products",
                          headers={"X-Forwarded-For": fake_ip,
                                   "User-Agent": f"botnet-{random.randint(1,5)}"},
                          name="/api/products [ddos]")


class BruteForceUser(HttpUser):
    """Hammer /api/login with bad credentials."""
    wait_time = between(0.05, 0.3)

    @task
    def login_attempt(self):
        fake_ip = f"198.51.100.{random.randint(1, 5)}"   # small attacker IP set
        victim  = random.choice(USERNAMES)
        self.client.post("/api/login",
                          json={"username": victim, "password": "guess" + str(random.randint(1, 9999))},
                          headers={"X-Forwarded-For": fake_ip, "User-Agent": "hydra/8.6"},
                          catch_response=True, name="/api/login [brute-force]") \
            .__enter__()


class SlowLorisUser(HttpUser):
    """Long-running requests."""
    wait_time = between(0.1, 0.3)

    @task
    def slow_request(self):
        # /api/stats can be tuned to be slow (synthetic chaos in routes.py).
        # Pair this load with DEMO_SLOW_RATE bumped on the api Deployment.
        self.client.get("/api/stats",
                          name="/api/stats [slow-loris]",
                          headers={"X-Forwarded-For": f"203.0.113.{random.randint(1, 30)}"},
                          timeout=60)


class SQLiUser(HttpUser):
    """SQL-injection-shaped paths. Should be blocked by WAF."""
    wait_time = between(0.5, 2.0)

    @task
    def malicious_path(self):
        payload = random.choice(SQLI_PAYLOADS)
        params  = urlencode({"q": payload})
        self.client.get(f"/api/products?{params}",
                          headers={"X-Forwarded-For": f"198.51.100.{random.randint(1, 30)}",
                                   "User-Agent": "sqlmap/1.7"},
                          name="/api/products?q=... [sqli]")


# ─── Pick the right user class based on env ─────────────────────────────────

if MODE == "attack":
    USER_CLASSES = {
        "ddos":         [DDosUser],
        "brute-force":  [BruteForceUser],
        "slow-loris":   [SlowLorisUser],
        "sqli":         [SQLiUser],
    }
    if ATTACK in USER_CLASSES:
        # locust uses every HttpUser subclass it finds, so disable the others by
        # marking them abstract.
        for name in ("NormalUser", "DDosUser", "BruteForceUser", "SlowLorisUser", "SQLiUser"):
            cls = globals()[name]
            cls.abstract = cls not in USER_CLASSES[ATTACK]
    else:
        raise ValueError(f"Unknown DEMO_ATTACK: {ATTACK!r}; valid: {list(USER_CLASSES)}")
else:
    # Normal mode — only NormalUser; mark attackers abstract.
    for name in ("DDosUser", "BruteForceUser", "SlowLorisUser", "SQLiUser"):
        globals()[name].abstract = True


@events.quitting.add_listener
def _summary(environment, **_kwargs):
    stats = environment.stats
    print(f"\n=== Mode={MODE} attack={ATTACK} p99={stats.total.get_response_time_percentile(0.99):.0f}ms err={stats.total.fail_ratio:.2%} ===")
