# Copilot License Manager

Bulk assign GitHub Copilot licenses to organization members using a CSV file.

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Python** | 3.8 or later |
| **GitHub PAT** | Fine-grained token with **"GitHub Copilot Business" write** permission |
| **Org Admin** | You must be an **owner** of the GitHub organization |
| **Copilot Plan** | Organization must have an active Copilot Business or Enterprise subscription |

## Installation

```bash
git clone https://github.com/<your-org>/copilot-license-manager.git
cd copilot-license-manager
pip install -r requirements.txt
```

## Creating a GitHub Personal Access Token (PAT)

1. Go to **Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Click **Generate new token**
3. Set **Resource owner** to your organization
4. Under **Organization permissions**, grant:
   - **GitHub Copilot Business** → **Read and write**
   - **Members** → **Read-only** (needed for `--export-members`)
5. Click **Generate token** and copy it

### Set the token as an environment variable

```bash
# Linux / macOS
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"

# Windows (PowerShell)
$env:GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxx"

# Windows (CMD)
set GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
```

---

## Usage

### Step 1: Download the Enterprise People CSV

1. Sign in to your GitHub Enterprise account
2. Go to **`github.com/enterprises/<your-enterprise>/people`**
3. Click **Export as CSV** (top-right of the page)
4. Copy the downloaded CSV file into this repository folder

The export contains one row per enterprise member. The key column the script looks for is **`GitHub com login`** — the member's GitHub.com username.

### Step 2: Edit the CSV

Open the CSV file **from the repository folder** (where you copied it in Step 1) and **delete the rows for any users who should NOT receive a Copilot license**. Keep only the rows for users who should get a seat. **Save the file back to the same location** — no need to move it anywhere.

> **Tip:** Users who are enterprise-managed users with no GitHub.com account will have a blank `GitHub com login` cell — the script automatically skips those rows and tells you how many were skipped.

### Step 3: Assign Licenses

> **Note:** The GitHub API only supports Copilot seat assignment at the **organization** level — there is no enterprise-level assignment endpoint. If your users span multiple orgs, run the script once per org.

From the repository folder, run:

```bash
python assign_copilot_licenses.py --org <your-org-name> --csv <filename>.csv
```

Replace `<your-org-name>` and `<filename>.csv` with the actual org and file names.

**Options:**
| Flag | Description |
|---|---|
| `--csv <path>` | Path to the CSV file (required) |
| `--column <name>` | Column containing GitHub.com usernames (default: auto-detected from `GitHub com login`, `login`, `username`, `github_handle`) |
| `--batch-size <n>` | Users per API request (default: `50`) |
| `--token <pat>` | GitHub PAT (default: reads `GITHUB_TOKEN` env var) |
| `--yes` / `-y` | Skip the confirmation prompt (for CI/scripts) |

### Full Example Workflow

```bash
# 1. In your browser, go to:
#    https://github.com/enterprises/acme-corp/people
#    Click "Export as CSV" and save the file as acme_people.csv

# 2. Copy acme_people.csv into this directory.
#    Open it in Excel / a text editor, delete rows for users who should NOT
#    get Copilot, and save the file back in this same directory.

# 3. Assign licenses (script will show a preview + confirmation prompt)
python assign_copilot_licenses.py --org acme-corp --csv acme_people.csv

# 4. To skip the prompt in a CI/CD pipeline:
python assign_copilot_licenses.py --org acme-corp --csv acme_people.csv --yes
```

### Output

The script prints a pre-flight summary, batch progress, and a final status report:

```
============================================================
  Copilot Subscription — acme-corp
============================================================
  Plan type:              business
  Seat management:        assign_selected
  Total seats:            12
  Active this cycle:      10
  Added this cycle:       5
  Pending invitation:     0
  Pending cancellation:   0
============================================================

Loaded 3 unique usernames from 'acme_members.csv'

Assigning Copilot licenses to 3 users in 1 batch(es)...

  Batch 1/1: 3 users ... OK (2 new seats created)

Fetching current seat assignments for status report...

======================================================================
  Assignment Status Report
======================================================================
  Username     Status                Details
  ----------   --------------------  -------------------------
  alice        ASSIGNED              Since 2026-03-25
  bob          ASSIGNED              Since 2026-01-15
  charlie      NOT FOUND             Not in seat list — may not be an org member

  Summary: 2 assigned, 0 failed, 1 not found
  Total users processed: 3
======================================================================
```

---

## CSV Format

The script accepts the **GitHub Enterprise People export CSV** directly — no pre-processing required.

### Auto-detected columns

The script looks for a username column in this order (case-insensitive):

| Priority | Column name | Source |
|---|---|---|
| 1 | `GitHub com login` | GitHub Enterprise People export (standard) |
| 2 | `login` | GitHub API JSON / custom exports |
| 3 | `username` | Legacy format used by earlier versions of this tool |
| 4 | `github_handle` | Custom HR/IT system exports |

### Enterprise People export example

```csv
GitHub com login,GitHub com name,GitHub com profile,GitHub com two-factor auth,GitHub com enterprise managed user,Visual Studio subscription email,License type,acme-corp owner,acme-corp member,Total user accounts
alice,Alice Smith,https://github.com/alice,TRUE,FALSE,,Enterprise: User,TRUE,FALSE,1
bob,Bob Jones,https://github.com/bob,TRUE,FALSE,bob@company.com,Enterprise: Visual Studio subscriber,FALSE,TRUE,1
charlie,Charlie Brown,https://github.com/charlie,TRUE,FALSE,,Enterprise: User,FALSE,TRUE,1
```

Rows with a blank `GitHub com login` (enterprise-managed users with no GitHub.com account) are **automatically skipped** and counted in the summary.

### Overriding column auto-detection

If your CSV uses a different column name, pass `--column`:

```bash
python assign_copilot_licenses.py --org my-org --csv users.csv --column github_handle
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `401 Requires authentication` | Token is invalid or expired | Generate a new PAT |
| `403 Forbidden` | Not an org owner, or token lacks required scopes | Check PAT scopes and org ownership |
| `404 Resource not found` | Org doesn't exist or Copilot not enabled | Verify org name and Copilot subscription |
| `422 Unprocessable Entity` | Copilot not configured, billing not set up, or seat management set to "all users" | Go to org Copilot settings and set access to "Selected members" |
| `Could not auto-detect a username column` | CSV doesn't contain any of the known column names | Pass `--column <name>` with the exact column header from your CSV |

---

## License

MIT
