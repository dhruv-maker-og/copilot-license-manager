#!/usr/bin/env python3
"""
Bulk GitHub Copilot License Assignment Tool

Assigns GitHub Copilot seats to organization members in bulk from a CSV file,
and reports assignment status. Can also export org members to CSV for easy editing.

Usage:
    # Export org members to CSV
    python assign_copilot_licenses.py --org my-org --export-members --output members.csv

    # Assign licenses from CSV
    python assign_copilot_licenses.py --org my-org --csv members.csv
"""

import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

import requests

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"


def get_headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
    }


# ── Export Org Members ───────────────────────────────────────────────────────


def export_org_members(org, token, output_path, role_filter="all"):
    """Fetch all organization members and write them to a CSV file."""
    headers = get_headers(token)
    members = []
    page = 1

    print(f"Fetching members of '{org}' (role={role_filter})...")

    while True:
        resp = requests.get(
            f"{API_BASE}/orgs/{org}/members",
            headers=headers,
            params={"per_page": 100, "page": page, "role": role_filter},
            timeout=30,
        )
        if resp.status_code == 401:
            print("ERROR: Authentication failed. Check your GitHub token.")
            sys.exit(1)
        if resp.status_code == 403:
            print("ERROR: Forbidden. Your token lacks permission to list org members.")
            sys.exit(1)
        if resp.status_code == 404:
            print(f"ERROR: Organization '{org}' not found.")
            sys.exit(1)
        resp.raise_for_status()

        batch = resp.json()
        if not batch:
            break
        members.extend(batch)
        page += 1

    if not members:
        print("No members found.")
        return

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["username", "id", "type"])
        for m in members:
            writer.writerow([m["login"], m["id"], m["type"]])

    print(f"Exported {len(members)} members to '{output_path}'")
    print("Edit the CSV to keep only the users you want to assign Copilot licenses to,")
    print("then run:  python assign_copilot_licenses.py --org <ORG> --csv " + output_path)


# ── Pre-flight Check ─────────────────────────────────────────────────────────


def preflight_check(org, token):
    """Verify Copilot is enabled and show current seat breakdown."""
    headers = get_headers(token)
    resp = requests.get(
        f"{API_BASE}/orgs/{org}/copilot/billing",
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 401:
        print("ERROR: Authentication failed. Check your GitHub token.")
        sys.exit(1)
    if resp.status_code == 403:
        print("ERROR: Forbidden. You must be an org owner to manage Copilot licenses.")
        sys.exit(1)
    if resp.status_code == 404:
        print(f"ERROR: Organization '{org}' not found or Copilot is not enabled.")
        sys.exit(1)
    if resp.status_code == 422:
        print("ERROR: Billing is not set up for this organization.")
        sys.exit(1)
    resp.raise_for_status()

    data = resp.json()
    breakdown = data.get("seat_breakdown", {})

    print("=" * 60)
    print(f"  Copilot Subscription — {org}")
    print("=" * 60)
    print(f"  Plan type:              {data.get('plan_type', 'N/A')}")
    print(f"  Seat management:        {data.get('seat_management_setting', 'N/A')}")
    print(f"  Total seats:            {breakdown.get('total', 'N/A')}")
    print(f"  Active this cycle:      {breakdown.get('active_this_cycle', 'N/A')}")
    print(f"  Added this cycle:       {breakdown.get('added_this_cycle', 'N/A')}")
    print(f"  Pending invitation:     {breakdown.get('pending_invitation', 'N/A')}")
    print(f"  Pending cancellation:   {breakdown.get('pending_cancellation', 'N/A')}")
    print("=" * 60)
    print()

    return data


# ── Read CSV ──────────────────────────────────────────────────────────────────


def read_usernames_from_csv(csv_path, column):
    """Read and deduplicate usernames from a CSV file."""
    if not os.path.isfile(csv_path):
        print(f"ERROR: CSV file not found: {csv_path}")
        sys.exit(1)

    usernames = []
    seen = set()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if column not in (reader.fieldnames or []):
            print(f"ERROR: Column '{column}' not found in CSV.")
            print(f"  Available columns: {reader.fieldnames}")
            sys.exit(1)

        for row in reader:
            username = row[column].strip()
            if username and username.lower() not in seen:
                usernames.append(username)
                seen.add(username.lower())

    if not usernames:
        print("ERROR: No usernames found in CSV.")
        sys.exit(1)

    return usernames


# ── Assign Licenses ──────────────────────────────────────────────────────────


def assign_licenses(org, token, usernames, batch_size):
    """Assign Copilot licenses in batches. Returns (total_created, failed_users)."""
    headers = get_headers(token)
    total_created = 0
    failed_users = []

    batches = [usernames[i : i + batch_size] for i in range(0, len(usernames), batch_size)]
    print(f"Assigning Copilot licenses to {len(usernames)} users in {len(batches)} batch(es)...")
    print()

    for idx, batch in enumerate(batches, 1):
        print(f"  Batch {idx}/{len(batches)}: {len(batch)} users ... ", end="", flush=True)

        resp = requests.post(
            f"{API_BASE}/orgs/{org}/copilot/billing/selected_users",
            headers=headers,
            json={"selected_usernames": batch},
            timeout=60,
        )

        if resp.status_code == 201:
            data = resp.json()
            seats = data.get("seats_created", 0)
            total_created += seats
            print(f"OK ({seats} new seats created)")
        else:
            error_msg = ""
            try:
                error_msg = resp.json().get("message", resp.text)
            except Exception:
                error_msg = resp.text
            print(f"FAILED (HTTP {resp.status_code}: {error_msg})")
            failed_users.extend(batch)

    print()
    return total_created, failed_users


# ── Status Report ─────────────────────────────────────────────────────────────


def fetch_all_seats(org, token):
    """Fetch all current Copilot seat assignments (paginated)."""
    headers = get_headers(token)
    seats = []
    page = 1

    while True:
        resp = requests.get(
            f"{API_BASE}/orgs/{org}/copilot/billing/seats",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  Warning: Could not fetch seats (HTTP {resp.status_code}). Status report may be incomplete.")
            break

        data = resp.json()
        batch = data.get("seats", [])
        if not batch:
            break
        seats.extend(batch)
        page += 1

    return seats


def print_status_report(usernames, failed_users, seats):
    """Print a per-user status table after assignment."""
    # Build a lookup: lowercase login -> seat info
    seat_lookup = {}
    for seat in seats:
        assignee = seat.get("assignee", {})
        login = assignee.get("login", "").lower()
        if login:
            seat_lookup[login] = seat

    failed_set = {u.lower() for u in failed_users}

    assigned_count = 0
    already_count = 0
    failed_count = 0

    col_user = "Username"
    col_status = "Status"
    col_detail = "Details"
    max_user = max(len(col_user), max(len(u) for u in usernames))

    print("=" * 70)
    print("  Assignment Status Report")
    print("=" * 70)
    print(f"  {col_user:<{max_user}}   {col_status:<20}  {col_detail}")
    print(f"  {'-' * max_user}   {'-' * 20}  {'-' * 25}")

    for username in usernames:
        if username.lower() in failed_set:
            status = "FAILED"
            detail = "API error (see batch output above)"
            failed_count += 1
        elif username.lower() in seat_lookup:
            seat = seat_lookup[username.lower()]
            pending = seat.get("pending_cancellation_date")
            if pending:
                status = "PENDING_CANCEL"
                detail = f"Cancels on {pending}"
            else:
                created = seat.get("created_at", "")
                status = "ASSIGNED"
                detail = f"Since {created[:10]}" if created else ""
            assigned_count += 1
        else:
            status = "NOT_FOUND"
            detail = "Not in seat list — may not be an org member"
            failed_count += 1

    # Re-print with counts (we iterated once to get counts, now print)
    # Actually let's just print inline above. Let me refactor:

    # Reset counters and reprint
    assigned_count = 0
    failed_count = 0
    not_found_count = 0

    rows = []
    for username in usernames:
        if username.lower() in failed_set:
            rows.append((username, "FAILED", "API error (see batch output above)"))
            failed_count += 1
        elif username.lower() in seat_lookup:
            seat = seat_lookup[username.lower()]
            pending = seat.get("pending_cancellation_date")
            if pending:
                rows.append((username, "PENDING_CANCEL", f"Cancels on {pending}"))
            else:
                created = seat.get("created_at", "")
                detail = f"Since {created[:10]}" if created else ""
                rows.append((username, "ASSIGNED", detail))
            assigned_count += 1
        else:
            rows.append((username, "NOT FOUND", "Not in seat list — may not be an org member"))
            not_found_count += 1

    for user, status, detail in rows:
        print(f"  {user:<{max_user}}   {status:<20}  {detail}")

    print()
    print(f"  Summary: {assigned_count} assigned, {failed_count} failed, {not_found_count} not found")
    print(f"  Total users processed: {len(usernames)}")
    print("=" * 70)


# ── CLI ───────────────────────────────────────────────────────────────────────


def build_parser():
    parser = argparse.ArgumentParser(
        description="Bulk assign GitHub Copilot licenses to organization members.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export org members to a CSV file
  python assign_copilot_licenses.py --org my-org --export-members --output members.csv

  # Assign licenses from a CSV
  python assign_copilot_licenses.py --org my-org --csv users.csv

  # Assign with a custom column name and batch size
  python assign_copilot_licenses.py --org my-org --csv users.csv --column github_handle --batch-size 25
        """,
    )

    parser.add_argument("--org", required=True, help="GitHub organization name")
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub personal access token (default: reads GITHUB_TOKEN env var)",
    )

    # Mode: export members
    export_group = parser.add_argument_group("Export mode")
    export_group.add_argument(
        "--export-members",
        action="store_true",
        help="Export organization members to a CSV file instead of assigning licenses",
    )
    export_group.add_argument(
        "--output",
        default="members.csv",
        help="Output CSV path for --export-members (default: members.csv)",
    )
    export_group.add_argument(
        "--role",
        choices=["all", "admin", "member"],
        default="all",
        help="Filter members by role when exporting (default: all)",
    )

    # Mode: assign licenses
    assign_group = parser.add_argument_group("Assign mode")
    assign_group.add_argument("--csv", default=None, help="Path to CSV file with usernames")
    assign_group.add_argument(
        "--column",
        default="username",
        help="CSV column name containing GitHub usernames (default: username)",
    )
    assign_group.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of users per API request (default: 50)",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Resolve token
    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: No GitHub token provided.")
        print("  Set the GITHUB_TOKEN environment variable or use --token <PAT>")
        sys.exit(1)

    # ── Export Mode ──
    if args.export_members:
        export_org_members(args.org, token, args.output, args.role)
        return

    # ── Assign Mode ──
    if not args.csv:
        print("ERROR: Provide --csv <file> to assign licenses, or use --export-members.")
        parser.print_help()
        sys.exit(1)

    # Step 1: Pre-flight check
    print()
    preflight_check(args.org, token)

    # Step 2: Read usernames
    usernames = read_usernames_from_csv(args.csv, args.column)
    print(f"Loaded {len(usernames)} unique usernames from '{args.csv}'")
    print()

    # Step 3: Assign licenses
    total_created, failed_users = assign_licenses(
        args.org, token, usernames, args.batch_size
    )

    # Step 4: Fetch current seats for status report
    print("Fetching current seat assignments for status report...")
    seats = fetch_all_seats(args.org, token)
    print()

    # Step 5: Print status report
    print_status_report(usernames, failed_users, seats)

    # Exit with error code if any failures
    if failed_users:
        sys.exit(1)


if __name__ == "__main__":
    main()
