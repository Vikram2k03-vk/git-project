import os
import hmac
import hashlib
import subprocess
import tempfile
import shutil
from flask import Flask, request, jsonify, abort
from dotenv import load_dotenv

# ---------------- Load Environment Variables ----------------
load_dotenv()

APP_ID = os.getenv("APP_ID")                      # GitHub App ID
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")  # Webhook secret
PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH")  # Path to your private key

app = Flask(__name__)
errors = []


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


# ---------------- Webhook Endpoint ----------------
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Hub-Signature-256")
    if signature is None or not verify_signature(request.data, signature):
        abort(401, "Invalid signature")

    payload = request.json
    repo_url = payload["repository"]["clone_url"]

    # Clone repo into a temporary directory
    temp_dir = tempfile.mkdtemp()
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
                    else:
                        errors.append(f"✅ {file_path}: No errors")
                else:
                    errors.append(f"⚠️ {file_path}: File not found")

    # Cleanup temp folder
    shutil.rmtree(temp_dir)

    return jsonify({"status": "errors recorded"}), 200


# ---------------- Errors Page ----------------
@app.route("/errors", methods=["GET"])
def get_errors():
    return jsonify(errors)


# ---------------- Run Flask ----------------
if __name__ == "__main__":
    app.run(port=5000, debug=True)
