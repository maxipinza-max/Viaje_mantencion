#!/usr/bin/env python3
"""
Fetch Jira Polaris ideas from project VC and save to data/ideas.json.
Requires environment variables:
  JIRA_EMAIL      - Atlassian account email
  JIRA_API_TOKEN  - Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens)
"""

import json
import os
import sys
from base64 import b64encode
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import HTTPError

JIRA_BASE = "https://elevaap.atlassian.net"
PROJECT   = "VC"
FIELDS    = ",".join([
    "summary",
    "status",
    "customfield_10719",   # Viaje 2: Servicio de mantención
    "customfield_10733",   # Plataforma
    "customfield_10327",   # Estado de la entrega
    "customfield_10725",   # Objetivo del proyecto
    "customfield_10721",   # Segmentos de usuario
    "customfield_10732",   # Puntuacion RICE
    "customfield_10729",   # Descripción breve de la idea
])

DISCARD_VALUES = {"Un valor nuevo", "Sin valor"}


def get_auth_header():
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email or not token:
        print("ERROR: JIRA_EMAIL and JIRA_API_TOKEN must be set", file=sys.stderr)
        sys.exit(1)
    creds = b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def fetch_issues(headers):
    ideas = []
    next_page_token = None
    page_size = 100

    while True:
        params = {
            "jql": f"project = {PROJECT} AND issuetype = Idea ORDER BY created DESC",
            "fields": FIELDS,
            "maxResults": page_size,
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token

        # Use the new /search/jql endpoint (old /search was removed by Atlassian)
        url = f"{JIRA_BASE}/rest/api/3/search/jql?{urlencode(params)}"
        req = Request(url, headers=headers)

        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except HTTPError as e:
            print(f"HTTP {e.code}: {e.read().decode()}", file=sys.stderr)
            sys.exit(1)

        issues = data.get("issues", [])

        for issue in issues:
            fields = issue["fields"]

            # Parse objetivo_proyecto (interval field stored as JSON string)
            objetivo = None
            raw_obj = fields.get("customfield_10725")
            if raw_obj:
                if isinstance(raw_obj, str):
                    try:
                        objetivo = json.loads(raw_obj)
                    except json.JSONDecodeError:
                        objetivo = None
                elif isinstance(raw_obj, dict):
                    objetivo = raw_obj

            viaje2 = (fields.get("customfield_10719") or {}).get("value")

            # Skip ideas with placeholder/invalid values
            if viaje2 in DISCARD_VALUES:
                continue

            ideas.append({
                "key": issue["key"],
                "summary": fields.get("summary", ""),
                "status": (fields.get("status") or {}).get("name", ""),
                "viaje2": viaje2,
                "plataforma": [opt["value"] for opt in (fields.get("customfield_10733") or [])],
                "estado_entrega": fields.get("customfield_10327"),
                "objetivo_proyecto": objetivo,
                "segmentos_usuario": [opt["value"] for opt in (fields.get("customfield_10721") or [])],
                "rice_score": fields.get("customfield_10732"),
                "descripcion_breve": fields.get("customfield_10729"),
                "url": f"{JIRA_BASE}/jira/polaris/projects/{PROJECT}/ideas/idea/{issue['key']}",
            })

        next_page_token = data.get("nextPageToken")
        if not next_page_token or not issues:
            break

    return ideas


def main():
    headers = get_auth_header()
    print("Fetching ideas from Jira Polaris...")
    ideas = fetch_issues(headers)
    print(f"Fetched {len(ideas)} ideas")

    output = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(ideas),
        "ideas": ideas,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/ideas.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("Saved to data/ideas.json")


if __name__ == "__main__":
    main()
