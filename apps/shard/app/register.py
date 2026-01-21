from __future__ import annotations
import os, time
import requests

ROLE = "auto"
LEADER_URL = None

def get_role() -> str:
    return ROLE

def get_leader_url() -> str | None:
    return LEADER_URL

def try_register_forever():
    global ROLE, LEADER_URL

    coordinator = os.getenv("COORDINATOR_URL")
    shard_url = os.getenv("SHARD_URL")
    shard_name = os.getenv("SHARD_NAME", "shard-0")
    replica_id = os.getenv("REPLICA_ID", os.getenv("HOSTNAME", "replica"))

    if not coordinator or not shard_url:
        return

    interval = float(os.getenv("REGISTER_INTERVAL_SEC", "10"))
    url = f"{coordinator.rstrip('/')}/register-replica"

    while True:
        payload = {
            "shard_name": shard_name,
            "replica_url": shard_url.rstrip("/"),
            "replica_id": replica_id,
            "role": "auto"
        }
        try:
            r = requests.post(url, json=payload, timeout=5)
            if 200 <= r.status_code < 300:
                data = r.json()
                ROLE = data["assigned_role"]
                LEADER_URL = data["leader_url"].rstrip("/")
        except requests.RequestException:
            pass
        time.sleep(interval)
