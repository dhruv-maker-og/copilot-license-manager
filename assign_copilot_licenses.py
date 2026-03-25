#!/usr/bin/env python3
"""
Bulk GitHub Copilot License Assignment Tool

Assigns GitHub Copilot seats to organization members in bulk from a CSV file,
and reports assignment status.

Workflow:
    1. Go to GitHub Enterprise → People → Export as CSV
    2. Copy the downloaded CSV into this directory
    3. Open the CSV and DELETE rows for users who should NOT get Copilot; save
    4. Run: python assign_copilot_licenses.py --org my-org --csv people_export.csv
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

# Columns tried (in order) when --column is not explicitly specified.
# The first match found in the CSV header is used.
AUTO_DETECT_COLUMNS = ["GitHub com login", "login", "username", "github_handle"]


def get_headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
    }


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
    """Read and deduplicate usernames from a CSV file.

    If column is None, the username column is auto-detected by trying
    AUTO_DETECT_COLUMNS in order (case-insensitive). If column is explicitly
    provided via --column, it is used directly.

    Rows where the resolved column value is blank are silently skipped and
    counted (common for enterprise-managed users with no GitHub.com account).
    """
    if not os.path.isfile(csv_path):
        print(f"ERROR: CSV file not found: {csv_path}")
        sys.exit(1)

    usernames = []
    seen = set()
    skipped_blank = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        # Resolve which column to use
        if column is None:
            # Auto-detect: case-insensitive match against AUTO_DETECT_COLUMNS
            fieldnames_lower = {fn.strip().lower(): fn for fn in fieldnames}
            resolved_column = None
            for candidate in AUTO_DETECT_COLUMNS:
                if candidate.lower() in fieldnames_lower:
                    resolved_column = fieldnames_lower[candidate.lower()]
                    break
            if resolved_column is None:
                print("ERROR: Could not auto-detect a username column in the CSV.")
                print(f"  Tried (in order): {', '.join(repr(c) for c in AUTO_DETECT_COLUMNS)}")
                print(f"  Available columns: {fieldnames}")
                print("  Use --column <name> to specify the column explicitly.")
                sys.exit(1)
            print(f"Detected username column: '{resolved_column}'")
        else:
            # Explicit column — verify it exists
            if column not in fieldnames:
                print(f"ERROR: Column '{column}' not found in CSV.")
                print(f"  Available columns: {fieldnames}")
                sys.exit(1)
            resolved_column = column

        for row in reader:
            username = row[resolved_column].strip()
            if not username:
                skipped_blank += 1
                continue
            if username.lower() not in seen:
                usernames.append(username)
                seen.add(username.lower())

    if skipped_blank:
        print(f"  Note: Skipped {skipped_blank} row(s) with a blank '{resolved_column}' value.")

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
        description=(
            "Bulk assign GitHub Copilot licenses to organization members "
            "from a GitHub Enterprise People CSV export."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. Go to GitHub Enterprise \u2192 People \u2192 Export as CSV
  2. Copy the downloaded CSV into this directory
  3. Open the CSV and DELETE rows for users who should NOT get Copilot; save
  4. Run this script to assign licenses

Examples:
  # Assign licenses from an Enterprise People CSV export
  python assign_copilot_licenses.py --org my-org --csv enterprise_people.csv

  # Skip the confirmation prompt (useful in CI/CD pipelines)
  python assign_copilot_licenses.py --org my-org --csv enterprise_people.csv --yes

  # Override the auto-detected username column
  python assign_copilot_licenses.py --org my-org --csv users.csv --column github_handle

  # Use a custom batch size
  python assign_copilot_licenses.py --org my-org --csv enterprise_people.csv --batch-size 25
        """,
    )

    parser.add_argument("--org", required=True, help="GitHub organization name")
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub personal access token (default: reads GITHUB_TOKEN env var)",
    )

    assign_group = parser.add_argument_group("Assign options")
    assign_group.add_argument(
        "--csv",
        required=True,
        help="Path to CSV file (GitHub Enterprise People export or compatible format)",
    )
    assign_group.add_argument(
        "--column",
        default=None,
        help=(
            "CSV column containing GitHub.com usernames. "
            "If omitted, auto-detected from: "
            + ", ".join(repr(c) for c in AUTO_DETECT_COLUMNS)
        ),
    )
    assign_group.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of users per API request (default: 50)",
    )
    assign_group.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip the confirmation prompt before assigning licenses",
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

    # Step 1: Pre-flight check
    print()
    preflight_check(args.org, token)

    # Step 2: Read usernames from the Enterprise People CSV
    usernames = read_usernames_from_csv(args.csv, args.column)
    print(f"Loaded {len(usernames)} unique usernames from '{args.csv}'")
    print()

    # Step 3: Confirmation prompt
    if not args.yes:
        print(f"Users to be assigned Copilot licenses ({len(usernames)} total):")
        for u in usernames[:5]:
            print(f"  - {u}")
        if len(usernames) > 5:
            print(f"  ... and {len(usernames) - 5} more")
        print()
        try:
            answer = input(f"Assign Copilot licenses to {len(usernames)} user(s)? [y/N]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)
        if answer not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)
        print()

    # Step 4: Assign licenses
    total_created, failed_users = assign_licenses(
        args.org, token, usernames, args.batch_size
    )

    # Step 5: Fetch current seats for status report
    print("Fetching current seat assignments for status report...")
    seats = fetch_all_seats(args.org, token)
    print()

    # Step 6: Print status report
    print_status_report(usernames, failed_users, seats)

    # Exit with error code if any failures
    if failed_users:
        sys.exit(1)


if __name__ == "__main__":
    main()
