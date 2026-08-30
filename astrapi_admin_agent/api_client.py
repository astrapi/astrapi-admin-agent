# astrapi_admin_agent/api_client.py
"""Duenner HTTP-Client fuer die astrapi-admin Agent-API."""
import httpx


class ApiClient:
    @staticmethod
    def pair(server_url: str, pairing_token: str, hostname: str, os_type: str) -> dict:
        resp = httpx.post(
            f"{server_url.rstrip('/')}/api/agent/pair",
            json={"token": pairing_token, "hostname": hostname, "os_type": os_type},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def __init__(self, server_url: str, host_token: str):
        self._client = httpx.Client(
            base_url=server_url.rstrip("/"),
            headers={"Authorization": f"Bearer {host_token}"},
            timeout=30,
        )

    def get_policy(self) -> dict:
        r = self._client.get("/api/agent/policy")
        r.raise_for_status()
        return r.json()

    def report(self, status: str, summary: str, details: dict) -> dict:
        r = self._client.post(
            "/api/agent/report",
            json={"status": status, "summary": summary, "details": details},
        )
        r.raise_for_status()
        return r.json()
