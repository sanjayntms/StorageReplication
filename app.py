import os
import time
import requests
from datetime import datetime, timezone
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
)

from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError

# =====================================================================================
# CONFIG
# =====================================================================================

ACCOUNT_NAME = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "ntmssaudk")
ACCOUNT_KEY = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")
CONTAINER_NAME = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "media")

# ARM / StorageRP (for geoReplicationStats.lastSyncTime)
SUBSCRIPTION_ID = os.environ.get(
    "AZURE_SUBSCRIPTION_ID", "a0966ab9-54ed-40c3-927b-f64be45d0cee"
)
RESOURCE_GROUP = os.environ.get("AZURE_RESOURCE_GROUP", "storageEntra-RG")
STORERP_API_VERSION = os.environ.get("AZURE_STORERP_API_VERSION", "2023-01-01")

PRIMARY_BLOB_URL = f"https://{ACCOUNT_NAME}.blob.core.windows.net"
SECONDARY_BLOB_URL = f"https://{ACCOUNT_NAME}-secondary.blob.core.windows.net"

if not ACCOUNT_NAME or not ACCOUNT_KEY:
    raise RuntimeError(
        "AZURE_STORAGE_ACCOUNT_NAME and AZURE_STORAGE_ACCOUNT_KEY must be set."
    )

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "ragrs-demo-secret")

# Track upload timestamps (for *demo only*; real lag is account-level from ARM)
upload_times = {}

# =====================================================================================
# BLOB CLIENT (PRIMARY)
# =====================================================================================

primary_client = BlobServiceClient(
    account_url=PRIMARY_BLOB_URL,
    credential=ACCOUNT_KEY,
)
container_client = primary_client.get_container_client(CONTAINER_NAME)

# Create container once
try:
    container_client.create_container()
except ResourceExistsError:
    pass
except Exception as e:
    app.logger.warning(f"create_container ignored error: {e}")


# =====================================================================================
# MANAGED IDENTITY → ARM TOKEN
# =====================================================================================

def get_arm_token() -> str:
    """
    Get ARM access token using the VM's system-assigned managed identity.
    Scope/resource: https://management.azure.com/
    """
    imds_url = "http://169.254.169.254/metadata/identity/oauth2/token"
    params = {
        "api-version": "2018-02-01",
        "resource": "https://management.azure.com/",
    }
    headers = {"Metadata": "true"}

    resp = requests.get(imds_url, params=params, headers=headers, timeout=3)
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"]


# =====================================================================================
# ARM REST: geoReplicationStats.lastSyncTime → account-level lag
# =====================================================================================

def get_account_replication_lag_seconds():
    """
    Uses Storage RP Get Properties to read properties.geoReplicationStats.lastSyncTime.
    Lag ≈ now_utc - lastSyncTime (seconds).

    This is account-level RPO for RA-GRS, NOT per-blob status.
    """
    try:
        token = get_arm_token()
    except Exception as e:
        app.logger.warning(f"ARM token error: {e}")
        return None, f"ARM token error: {e}"

    resource_url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}"
        f"/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.Storage/storageAccounts/{ACCOUNT_NAME}"
    )

    params = {
        "api-version": STORERP_API_VERSION,
        "$expand": "geoReplicationStats",
    }

    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(resource_url, params=params, headers=headers, timeout=5)
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        app.logger.warning(f"StorageRP get-properties error: {e}")
        return None, f"StorageRP error: {e}"

    props = body.get("properties", {})
    geo = props.get("geoReplicationStats") or {}
    last_sync = geo.get("lastSyncTime")
    status = geo.get("status")

    if not last_sync:
        return None, f"LastSyncTime unavailable (status={status})"

    # Parse ISO time (handles trailing 'Z')
    try:
        if last_sync.endswith("Z"):
            last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
        else:
            last_sync_dt = datetime.fromisoformat(last_sync)
    except Exception as e:
        return None, f"LastSyncTime parse error: {e}"

    now_utc = datetime.now(timezone.utc)
    lag = (now_utc - last_sync_dt).total_seconds()
    if lag < 0:
        lag = 0.0

    return round(lag, 2), None


# =====================================================================================
# ROUTES
# =====================================================================================

@app.route("/")
def index():
    # List primary blobs
    try:
        primary_blobs = list(container_client.list_blobs())
    except Exception as e:
        primary_blobs = []
        flash(f"Error listing blobs: {e}", "error")

    items = []
    for blob in primary_blobs:
        name = blob.name
        items.append(
            {
                "name": name,
                "primary_url": f"{PRIMARY_BLOB_URL}/{CONTAINER_NAME}/{name}",
                "secondary_url": f"{SECONDARY_BLOB_URL}/{CONTAINER_NAME}/{name}",
            }
        )

    return render_template(
        "index.html",
        items=items,
        account_name=ACCOUNT_NAME,
        container_name=CONTAINER_NAME,
    )


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("Please select a file", "error")
        return redirect(url_for("index"))

    blob_name = file.filename

    try:
        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(file.stream, overwrite=True)
        upload_times[blob_name] = time.time()
        flash(f"Uploaded '{blob_name}' to primary", "success")
    except Exception as e:
        flash(f"Upload failed: {e}", "error")

    return redirect(url_for("index"))


@app.route("/api/account-latency")
def api_account_latency():
    """
    Returns account-level RA-GRS replication lag (seconds) based on
    geoReplicationStats.lastSyncTime from Storage RP.
    """
    lag, error = get_account_replication_lag_seconds()
    return jsonify(
        {
            "lag_seconds": lag,
            "error": error,
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    app.run(host="0.0.0.0", port=port, debug=True)

