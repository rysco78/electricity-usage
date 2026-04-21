"""
Smart Meter Texas consumer API client.
Base URL: https://smartmetertexas.com/api
Swagger:  https://github.com/keatontaylor/smartmetertexas-api

NOTE: The consumer API only supports on-demand reads (current meter state).
      Historical daily/interval data requires a Green Button XML download from
      https://www.smartmetertexas.com → My Account → Download My Data.
"""

import time
import requests

SMT_HOST   = "https://www.smartmetertexas.com"
SMT_API    = f"{SMT_HOST}/api"          # authenticated calls
SMT_COMMON = f"{SMT_HOST}/commonapi"    # public/auth calls

ODR_POLL_TIMEOUT  = 90
ODR_POLL_INTERVAL = 5


class SMTClient:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.token: str | None = None

    # Akamai bot detection blocks requests without browser-like headers
    _BROWSER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.smartmetertexas.com",
        "Referer": "https://www.smartmetertexas.com/home",
        "Content-Type": "application/json",
    }

    def authenticate(self) -> None:
        resp = requests.post(
            f"{SMT_COMMON}/user/authenticate",
            json={"username": self.username, "password": self.password, "rememberMe": "true"},
            headers={
                **self._BROWSER_HEADERS,
                "X-Amzn-Trace-Id": f"Service=Authenticate,Request-ID={self.username}",
            },
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        self.token = body.get("token")
        if not self.token:
            raise ValueError(f"Authentication failed: {body.get('errormessage', body)}")

    def _auth_headers(self) -> dict:
        if not self.token:
            self.authenticate()
        return {
            **self._BROWSER_HEADERS,
            "Authorization": f"Bearer {self.token}",
        }

    def request_odr(self, esi_id: str, meter_number: str) -> str:
        """Request an on-demand meter read. Returns correlationId."""
        # Bills show meter numbers like "163106093LG" but the API wants only
        # the numeric prefix — strip any trailing non-digit characters.
        meter_number = meter_number.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")

        resp = requests.post(
            f"{SMT_API}/ondemandread",
            headers=self._auth_headers(),
            json={"ESIID": esi_id, "MeterNumber": meter_number},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        payload = body.get("data", body) if isinstance(body, dict) else body
        correlation_id = (
            payload.get("correlationId")
            or payload.get("trans_id")
        )
        if not correlation_id:
            raise ValueError(f"ODR request failed — unexpected response: {body}")
        return correlation_id

    def get_latest_odr(self, esi_id: str) -> dict:
        """
        Fetch the latest completed on-demand read.
        Returns dict with keys: odrstatus, odrread, odrusage, odrdate.
        """
        resp = requests.post(
            f"{SMT_API}/usage/latestodrread",
            headers=self._auth_headers(),
            json={"ESIID": esi_id},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        return body.get("data", body) if isinstance(body, dict) else body
