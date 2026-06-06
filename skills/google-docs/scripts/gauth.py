#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Google Workspace authentication helper.

Standalone: prints an access token to stdout.
    uv run gauth.py token
    uv run gauth.py quota-project

Also provides get_auth_headers() / google_api() for inline import within
sibling scripts (they copy-paste the _auth_core block).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import requests

# ── Preferred defaults ───────────────────────────────────────────────
PREFERRED_PROJECT = "ck-orp-nick-dev"
ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"

ALL_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def reauth_command() -> str:
    return f"gcloud auth application-default login --scopes={','.join(ALL_SCOPES)}"


def set_quota_command(project: str | None = None) -> str:
    return f"gcloud auth application-default set-quota-project {project or '<YOUR_PROJECT_ID>'}"


def _read_quota_project() -> str | None:
    """Read quota_project_id from the ADC credentials file."""
    if not ADC_PATH.exists():
        return None
    try:
        data = json.loads(ADC_PATH.read_text())
        return data.get("quota_project_id") or None
    except Exception:
        return None


def _auto_set_quota_project() -> str | None:
    """Try to auto-set quota project. Returns project name or None."""
    project = PREFERRED_PROJECT
    if not project:
        try:
            result = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip() and result.stdout.strip() != "(unset)":
                project = result.stdout.strip()
        except Exception:
            pass
    if not project:
        return None
    try:
        result = subprocess.run(
            ["gcloud", "auth", "application-default", "set-quota-project", project],
            capture_output=True, text=True, timeout=10,
        )
        return project if result.returncode == 0 else None
    except Exception:
        return None


def get_access_token() -> str:
    """Get an access token via gcloud ADC."""
    try:
        result = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        print("ERROR: gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install", file=sys.stderr)
        sys.exit(1)
    if result.returncode != 0:
        print(
            f"ERROR: Failed to get access token.\n"
            f"Fix: Run:\n  {reauth_command()}\n\n"
            f"gcloud stderr: {result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)
    return result.stdout.strip()


def get_auth_headers() -> dict[str, str]:
    """Return HTTP headers dict with Authorization + quota project."""
    token = get_access_token()
    quota = _read_quota_project()
    if not quota:
        quota = _auto_set_quota_project()
        if not quota:
            print(
                f"WARNING: No quota project set. Some APIs may fail.\n"
                f"Fix: {set_quota_command()}",
                file=sys.stderr,
            )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if quota:
        headers["x-goog-user-project"] = quota
    return headers


def google_api(
    base_url: str,
    api_name: str,
    endpoint: str,
    method: str = "GET",
    body: dict | list | None = None,
) -> dict:
    """
    Make an authenticated request to a Google API.
    Returns parsed JSON.  Exits with error message on failure.
    """
    headers = get_auth_headers()
    url = f"{base_url}{endpoint}"

    kwargs: dict = {"headers": headers, "timeout": 60}
    if body is not None:
        kwargs["json"] = body

    resp = requests.request(method, url, **kwargs)

    if resp.ok:
        if not resp.content:
            return {}
        return resp.json()

    # ── Error handling ───────────────────────────────────────────────
    if resp.status_code == 403:
        try:
            err = resp.json()
        except Exception:
            err = {}
        reason = ""
        details = err.get("error", {}).get("details", [])
        if details:
            reason = details[0].get("reason", "")
        message = err.get("error", {}).get("message", resp.text)

        if reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT":
            print(
                f"ERROR: {api_name} API: insufficient scopes.\n"
                f"Fix:\n  {reauth_command()}\n  {set_quota_command(_read_quota_project())}",
                file=sys.stderr,
            )
            sys.exit(1)

        if reason == "SERVICE_DISABLED" or "quota project" in message.lower():
            fixed = _auto_set_quota_project()
            if fixed:
                headers["x-goog-user-project"] = fixed
                retry = requests.request(method, url, headers=headers, json=body, timeout=60)
                if retry.ok:
                    return retry.json() if retry.content else {}
            print(
                f"ERROR: {api_name} API: quota project required but auto-fix failed.\n"
                f"Fix:\n  {set_quota_command()}",
                file=sys.stderr,
            )
            sys.exit(1)

    print(f"ERROR: {api_name} API ({resp.status_code}): {resp.text}", file=sys.stderr)
    sys.exit(1)


# ── CLI entry point ──────────────────────────────────────────────────
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Google Workspace auth helper")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("token", help="Print an access token")
    sub.add_parser("quota-project", help="Print the current quota project")
    sub.add_parser("setup-info", help="Print full setup instructions")

    args = parser.parse_args()
    if args.command == "token":
        print(get_access_token())
    elif args.command == "quota-project":
        qp = _read_quota_project()
        if qp:
            print(qp)
        else:
            print("(not set)", file=sys.stderr)
            sys.exit(1)
    elif args.command == "setup-info":
        print(json.dumps({
            "reauth_command": reauth_command(),
            "set_quota_command": set_quota_command(),
            "all_scopes": ALL_SCOPES,
            "adc_path": str(ADC_PATH),
        }, indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
