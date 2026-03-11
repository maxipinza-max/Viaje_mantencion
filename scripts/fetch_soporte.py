#!/usr/bin/env python3
"""
Fetch Jira Software stories labeled 'Soporte' from project CO (board 175)
and save to data/soporte.json.

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
PROJECT   = "CO"
LABEL     = "Soporte"

# Board lane order for the dashboard
LANE_ORDER = ["POR HACER", "EN CURSO", "BLOQUEADO", "HECHO"]

# Map Jira status category key → dashboard lane
CATEGORY_TO_LANE = {
    "new":        "POR HACER",   # "To Do" category
    "indeterminate": "EN CURSO", # "In Progress" category
    "done":       "HECHO",       # "Done" category
}

# Override by lowercased status name (catches BLOQUEADO and non-standard names)
NAME_TO_LANE = {
    "bloqueado":   "BLOQUEADO",
    "blocked":     "BLOQUEADO",
    "impedido":    "BLOQUEADO",
    "por hacer":   "POR HACER",
    "to do":       "POR HACER",
    "abierto":     "POR HACER",
    "open":        "POR HACER",
    "en curso":    "EN CURSO",
    "en progreso": "EN CURSO",
    "in progress": "EN CURSO",
    "in review":   "EN CURSO",
    "en revisión": "EN CURSO",
    "en revision": "EN CURSO",
    "hecho":       "HECHO",
    "done":        "HECHO",
    "cerrado":     "HECHO",
    "closed":      "HECHO",
    "resuelto":    "HECHO",
    "resolved":    "HECHO",
}


def get_auth_header():
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email or not token:
        print("ERROR: JIRA_EMAIL and JIRA_API_TOKEN must be set", file=sys.stderr)
        sys.exit(1)
    creds = b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def jira_get(headers, path, params=None):
    url = f"{JIRA_BASE}{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        print(f"HTTP {e.code} on {url}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def status_to_lane(status_name: str, category_key: str) -> str:
    """Resolve Jira status → dashboard lane with name override taking priority."""
    by_name = NAME_TO_LANE.get(status_name.lower().strip())
    if by_name:
        return by_name
    return CATEGORY_TO_LANE.get(category_key, "POR HACER")


def fetch_stories(headers):
    stories = []
    start_at = 0
    page_size = 100

    while True:
        params = {
            "jql": (
                f'project = "{PROJECT}" '
                f'AND labels = "{LABEL}" '
                f'AND issuetype in (Story, Task, Bug, "Historia") '
                f"ORDER BY created DESC"
            ),
            "fields": "summary,status,parent,customfield_10014,issuetype",
            "maxResults": page_size,
            "startAt": start_at,
        }

        data = jira_get(headers, "/rest/api/3/search", params)
        issues = data.get("issues", [])

        for issue in issues:
            fields = issue["fields"]
            status      = fields.get("status") or {}
            status_name = status.get("name", "")
            category    = (status.get("statusCategory") or {}).get("key", "new")
            lane        = status_to_lane(status_name, category)

            # Epic: try parent field (next-gen) then Epic Link custom field (classic)
            epic_key  = None
            epic_name = None

            parent = fields.get("parent")
            if parent:
                parent_type = (parent.get("fields") or {}).get("issuetype", {}).get("name", "")
                if parent_type == "Epic":
                    epic_key  = parent.get("key")
                    epic_name = (parent.get("fields") or {}).get("summary")

            # Classic Epic Link (customfield_10014 = epic key string)
            if not epic_key:
                epic_link_key = fields.get("customfield_10014")
                if epic_link_key:
                    epic_key  = epic_link_key
                    epic_name = epic_link_key  # name resolved below

            stories.append({
                "key":        issue["key"],
                "summary":    fields.get("summary", ""),
                "status":     status_name,
                "lane":       lane,
                "epic_key":   epic_key,
                "epic_name":  epic_name,
                "url":        f"{JIRA_BASE}/browse/{issue['key']}",
            })

        start_at += len(issues)
        total = data.get("total", 0)
        if start_at >= total or not issues:
            break

    return stories


def enrich_epic_names(headers, stories):
    """Resolve epic keys without names into epic summaries (one batch request)."""
    keys_to_resolve = list({
        s["epic_key"]
        for s in stories
        if s["epic_key"] and not s["epic_name"]
    })
    if not keys_to_resolve:
        return

    jql = "issueKey in (" + ",".join(keys_to_resolve) + ")"
    data = jira_get(headers, "/rest/api/3/search", {
        "jql": jql, "fields": "summary", "maxResults": len(keys_to_resolve)
    })
    name_map = {i["key"]: i["fields"].get("summary", i["key"]) for i in data.get("issues", [])}

    for s in stories:
        if s["epic_key"] and not s["epic_name"]:
            s["epic_name"] = name_map.get(s["epic_key"], s["epic_key"])


def main():
    headers = get_auth_header()
    print(f"Fetching stories labeled '{LABEL}' from project {PROJECT}...")
    stories = fetch_stories(headers)
    print(f"Fetched {len(stories)} stories")

    enrich_epic_names(headers, stories)

    output = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(stories),
        "stories": stories,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/soporte.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("Saved to data/soporte.json")


if __name__ == "__main__":
    main()
