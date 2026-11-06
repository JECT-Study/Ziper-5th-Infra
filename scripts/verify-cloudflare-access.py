#!/usr/bin/env python3
"""Read-only token/account/zone checks. Never log token values or API bodies."""

import datetime
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    report = {"checkedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "scope": "Read-only Cloudflare access; deployment write access is unverified",
              "checks": {}, "writeAccessVerified": False}
    stage = "configuration"
    status = None
    try:
        token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        zone = os.environ.get("CLOUDFLARE_ZONE_NAME", "")
        if not token or not re.fullmatch(r"[a-f0-9]{32}", account):
            raise ValueError("Invalid configuration")
        if not re.fullmatch(r"[a-z0-9.-]+", zone):
            raise ValueError("Invalid zone")
        opener = urllib.request.build_opener(NoRedirect())

        def get(path):
            nonlocal status
            request = urllib.request.Request(
                "https://api.cloudflare.com/client/v4" + path,
                headers={"Authorization": "Bearer " + token,
                         "Accept": "application/json"},
            )
            with opener.open(request, timeout=20) as response:
                status = response.status
                data = json.load(response)
            if data.get("success") is not True:
                raise ValueError("API request rejected")
            return data["result"]

        stage = "tokenActive"
        if get("/user/tokens/verify").get("status") != "active":
            raise ValueError("Inactive token")
        report["checks"][stage] = True
        stage = "accountReadable"
        if get("/accounts/" + account).get("id") != account:
            raise ValueError("Unexpected account")
        report["checks"][stage] = True
        stage = "workersReadable"
        if not isinstance(get("/accounts/" + account + "/workers/scripts"), list):
            raise ValueError("Unexpected scripts response")
        report["checks"][stage] = True
        stage = "zoneReadable"
        matches = get("/zones?" + urllib.parse.urlencode({"name": zone}))
        matches = [item for item in matches if item.get("name") == zone
                   and item.get("account", {}).get("id") == account]
        if len(matches) != 1 or not re.fullmatch(r"[a-f0-9]{32}", matches[0]["id"]):
            raise ValueError("Zone not visible in selected account")
        report["checks"][stage] = True
        stage = "routesReadable"
        if not isinstance(get("/zones/" + matches[0]["id"] + "/workers/routes"), list):
            raise ValueError("Unexpected routes response")
        report["checks"][stage] = True
        report["result"] = "passed"
    except Exception as error:
        report["result"] = "failed"
        report["failedCheck"] = stage
        report["httpStatus"] = error.code if isinstance(error, urllib.error.HTTPError) else status
    output = Path("dist/cloudflare-access.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    if report["result"] != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main()
