import os
import hmac
import hashlib
import subprocess
import tempfile
import shutil
import stat
import logging
from flask import Flask, request, jsonify, abort
from dotenv import load_dotenv

# ---------------- Load Environment Variables ----------------
load_dotenv()

APP_ID = os.getenv("APP_ID")                        # GitHub App ID
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")  # Webhook secret
PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH")    # Path to your private key

app = Flask(__name__)
errors = []

# ---------------- Logging Setup ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ---------------- Syntax Checker ----------------
def check_syntax(file_path):
    """Check syntax of a Python file and return error if any."""
    try:
        with open(file_path, "r") as f:
            code = f.read()
        compile(code, file_path, 'exec')  # Python syntax validation
        return None
    except SyntaxError as e:
        return f"❌ Error in {file_path} at line {e.lineno}: {e.msg}"


# ---------------- Verify Webhook Signature ----------------
def verify_signature(payload, signature):
    """Verify webhook HMAC signature from GitHub."""
    mac = hmac.new(WEBHOOK_SECRET.encode(), msg=payload, digestmod=hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected, signature)


# ---------------- Windows-Safe Cleanup ----------------
def remove_readonly(func, path, _):
    """Helper for read-only files on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def safe_rmtree(path):
    """Safely remove a directory tree."""
    if os.path.exists(path):
        shutil.rmtree(path, onerror=remove_readonly)


# ---------------- Webhook Endpoint ----------------
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Hub-Signature-256")
    if signature is None or not verify_signature(request.data, signature):
        logging.error("❌ Invalid webhook signature")
        abort(401, "Invalid signature")

    payload = request.json
    repo_url = payload["repository"]["clone_url"]
    logging.info(f"🔄 Received push event from repo: {repo_url}")

    # Clone repo into a temporary directory
    temp_dir = tempfile.mkdtemp()
    logging.info(f"📂 Cloning repository into {temp_dir}")
    subprocess.run(["git", "clone", repo_url, temp_dir], check=True)

    # Loop through commits → check added/modified files
    for commit in payload.get("commits", []):
        for file_path in commit.get("added", []) + commit.get("modified", []):
            if file_path.endswith(".py"):  # only check Python files
                abs_path = os.path.join(temp_dir, file_path)
                if os.path.exists(abs_path):
                    error = check_syntax(abs_path)
                    if error:
                        errors.append(error)
                        logging.error(error)
                    else:
                        msg = f"✅ {file_path}: No errors"
                        errors.append(msg)
                        logging.info(msg)
                else:
                    msg = f"⚠️ {file_path}: File not found in repo"
                    errors.append(msg)
                    logging.warning(msg)

    # Cleanup temp folder
    logging.info(f"🧹 Cleaning up {temp_dir}")
    safe_rmtree(temp_dir)

    return jsonify({"status": "completed", "errors_found": len(errors)}), 200


# ---------------- Errors Page ----------------
@app.route("/errors", methods=["GET"])
def get_errors():
    return jsonify(errors)


# ---------------- Run Flask ----------------
if __name__ == "__main__":
    logging.info("🚀 Starting Flask GitHub App Listener on port 5000")
    app.run(port=5000, debug=True)
