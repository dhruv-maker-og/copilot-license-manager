# Copilot License Manager

Bulk assign GitHub Copilot licenses to organization members using a CSV file.

---

## Prerequisites

| Requirement | Details |
|---|---|
| **Python** | 3.8 or later |
| **GitHub PAT** | With `manage_billing:copilot` scope (classic) or **"GitHub Copilot Business" write** permission (fine-grained) |
| **Org Admin** | You must be an **owner** of the GitHub organization |
| **Copilot Plan** | Organization must have an active Copilot Business or Enterprise subscription |

## Installation

```bash
git clone https://github.com/<your-org>/copilot-license-manager.git
cd copilot-license-manager
pip install -r requirements.txt
```

## Creating a GitHub Personal Access Token (PAT)

### Option A: Fine-grained PAT (recommended)

1. Go to **Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Click **Generate new token**
3. Set **Resource owner** to your organization
4. Under **Organization permissions**, grant:
   - **GitHub Copilot Business** → **Read and write**
   - **Members** → **Read-only** (needed for `--export-members`)
5. Click **Generate token** and copy it

### Option B: Classic PAT

1. Go to **Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Click **Generate new token**
3. Select scopes:
   - `manage_billing:copilot`
   - `read:org`
   - `admin:org` (if `manage_billing:copilot` is not available)
4. Click **Generate token** and copy it

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

### Step 1: Export Organization Members to CSV

Instead of manually creating a CSV, pull the member list directly from your org:

```bash
python assign_copilot_licenses.py --org my-org --export-members --output members.csv
```

This creates `members.csv` with columns: `username`, `id`, `type`.

**Options:**
| Flag | Description |
|---|---|
| `--output <path>` | Output file path (default: `members.csv`) |
| `--role <all\|admin\|member>` | Filter by org role (default: `all`) |

**Example output:**
```
username,id,type
alice,12345,User
bob,67890,User
charlie,11111,User
```

### Step 2: Edit the CSV

Open `members.csv` and **remove any users** you do NOT want to assign Copilot licenses to. Keep only the rows for users who should receive a license.

> **Tip:** The only required column is `username`. You can delete the `id` and `type` columns if you want a cleaner file.

### Step 3: Assign Licenses

```bash
python assign_copilot_licenses.py --org my-org --csv members.csv
```

**Options:**
| Flag | Description |
|---|---|
| `--csv <path>` | Path to CSV file with usernames (required) |
| `--column <name>` | Column name containing GitHub usernames (default: `username`) |
| `--batch-size <n>` | Users per API request (default: `50`) |
| `--token <pat>` | GitHub PAT (default: reads `GITHUB_TOKEN` env var) |

### Full Example Workflow

```bash
# 1. Export all org members
python assign_copilot_licenses.py --org acme-corp --export-members --output acme_members.csv

# 2. Edit acme_members.csv (remove users who shouldn't get Copilot)

# 3. Assign licenses
python assign_copilot_licenses.py --org acme-corp --csv acme_members.csv
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

The CSV must have a header row. By default the script looks for a column named `username`:

```csv
username
alice
bob
charlie
```

If your CSV uses a different column name (e.g., `github_handle`), specify it:

```bash
python assign_copilot_licenses.py --org my-org --csv users.csv --column github_handle
```

---

## How to Test

### 1. Dry-run with `--export-members` (safe, read-only)

Start by testing the export feature — this only **reads** data and does not assign anything:

```bash
python assign_copilot_licenses.py --org YOUR-ORG --export-members --output test_members.csv
```

**Verify:** Check that `test_members.csv` contains your org members.

### 2. Test with a small CSV (1-2 users)

Create a test CSV with just 1-2 users who should receive licenses:

```csv
username
your-test-user
```

```bash
python assign_copilot_licenses.py --org YOUR-ORG --csv test_small.csv
```

**Verify:** 
- Pre-flight summary prints without errors
- Batch output shows `OK` with seats created
- Status report shows `ASSIGNED` for the test user
- Check in GitHub UI: **Organization Settings → Copilot → Access** to confirm the seat

### 3. Test error scenarios

| Test | How | Expected result |
|---|---|---|
| Bad token | `--token invalid_token_here` | `ERROR: Authentication failed` |
| Wrong org | `--org nonexistent-org-xyz` | `ERROR: Organization 'nonexistent-org-xyz' not found` |
| Bad CSV column | `--column wrong_column` | `ERROR: Column 'wrong_column' not found in CSV` |
| Missing CSV file | `--csv nonexistent.csv` | `ERROR: CSV file not found` |
| Non-member user | Put a non-org-member in CSV | Status report shows `NOT FOUND` |
| Already assigned | Re-run the same CSV | Batch shows `0 new seats created`, status shows `ASSIGNED` |

### 4. Verify in GitHub UI

After running the script, confirm assignments in:
**github.com → Organization → Settings → Copilot → Access management**

### 5. Unit test with mocked API (advanced)

For CI/CD integration, you can mock the GitHub API responses using `unittest.mock` or `responses` library. The key functions to mock:

```python
# In your test file
from unittest.mock import patch
import assign_copilot_licenses as alc

@patch("assign_copilot_licenses.requests.post")
@patch("assign_copilot_licenses.requests.get")
def test_assign(mock_get, mock_post):
    # Mock preflight
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "plan_type": "business",
        "seat_management_setting": "assign_selected",
        "seat_breakdown": {"total": 10, "active_this_cycle": 8}
    }
    # Mock assignment
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {"seats_created": 2}
    
    # Run and assert...
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `401 Requires authentication` | Token is invalid or expired | Generate a new PAT |
| `403 Forbidden` | Not an org owner, or token lacks required scopes | Check PAT scopes and org ownership |
| `404 Resource not found` | Org doesn't exist or Copilot not enabled | Verify org name and Copilot subscription |
| `422 Unprocessable Entity` | Copilot not configured, billing not set up, or seat management set to "all users" | Go to org Copilot settings and set access to "Selected members" |

---

## License

MIT
