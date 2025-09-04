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

# Load Environment Variables
load_dotenv()

APP_ID = os.getenv("APP_ID")                        # GitHub App ID
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")  # Webhook secret
PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH")    # Path to your private key

app = Flask(__name__)
errors = []

# Logging Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

#Syntax Checker
def check_syntax(file_path):
    try:
        with open(file_path, "r") as f:
            code = f.read()
        compile(code, file_path, 'exec')  # Python syntax validation
        return None
    except SyntaxError as e:
        return f"Syntax Error in {file_path} at line {e.lineno}: {e.msg}"

#Runtime Checker
def run_file(file_path):
    try:
        result = subprocess.run(
            ["python", file_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return f"Runtime error in {file_path}:\n{result.stderr.strip()}"
        if result.stdout.strip():
            return f"Output from {file_path}:\n{result.stdout.strip()}"
        return None
    except subprocess.TimeoutExpired:
        return f"Timeout while running {file_path} (possible infinite loop)"

#Verify Webhook Signature
def verify_signature(payload, signature):
    mac = hmac.new(WEBHOOK_SECRET.encode(), msg=payload, digestmod=hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected, signature)

#Windows-Safe Cleanup
def remove_readonly(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)

def safe_rmtree(path):
    if os.path.exists(path):
        shutil.rmtree(path, onerror=remove_readonly)

# Common repo check logic
def run_checks_on_repo(temp_dir):
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(".py"):
                abs_path = os.path.join(root, file)
                error = check_syntax(abs_path)
                if error:
                    errors.append(error)
                    logging.error(error)
                else:
                    runtime_error = run_file(abs_path)
                    if runtime_error:
                        errors.append(runtime_error)
                        logging.error(runtime_error)
                    else:
                        msg = f"{file}: No errors"
                        errors.append(msg)
                        logging.info(msg)

# Push Handler
def handle_push(payload):
    repo_url = payload["repository"]["clone_url"]
    logging.info(f"Received push event from repo: {repo_url}")

    temp_dir = tempfile.mkdtemp()
    logging.info(f"Cloning repository into {temp_dir}")
    subprocess.run(["git", "clone", repo_url, temp_dir], check=True)

    for commit in payload.get("commits", []):
        for file_path in commit.get("added", []) + commit.get("modified", []):
            if file_path.endswith(".py"):
                abs_path = os.path.join(temp_dir, file_path)
                if os.path.exists(abs_path):
                    error = check_syntax(abs_path)
                    if error:
                        errors.append(error)
                        logging.error(error)
                    else:
                        runtime_error = run_file(abs_path)
                        if runtime_error:
                            errors.append(runtime_error)
                            logging.error(runtime_error)
                        else:
                            msg = f"{file_path}: No errors"
                            errors.append(msg)
                            logging.info(msg)
                else:
                    msg = f"{file_path}: File not found in repo"
                    errors.append(msg)
                    logging.warning(msg)

    logging.info(f"Cleaning up {temp_dir}")
    safe_rmtree(temp_dir)

    return jsonify({"status": "push checked", "errors_found": len(errors), "details": errors}), 200

# Pull Request Handler
def handle_pull_request(payload):
    action = payload["action"]
    pr_number = payload["number"]
    repo_url = payload["repository"]["clone_url"]

    logging.info(f"Pull Request #{pr_number} {action} in {repo_url}")

    if action not in ["opened", "synchronize", "reopened"]:
        return jsonify({"status": "skipped"}), 200

    temp_dir = tempfile.mkdtemp()
    pr_branch = payload["pull_request"]["head"]["ref"]

    logging.info(f"Cloning PR branch {pr_branch} into {temp_dir}")
    subprocess.run(["git", "clone", "--branch", pr_branch, repo_url, temp_dir], check=True)

    run_checks_on_repo(temp_dir)

    logging.info(f"Cleaning up {temp_dir}")
    safe_rmtree(temp_dir)

    return jsonify({"status": "PR checked", "errors_found": len(errors), "details": errors}), 200

# Webhook Router
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Hub-Signature-256")
    if signature is None or not verify_signature(request.data, signature):
        logging.error("Invalid webhook signature")
        abort(401, "Invalid signature")

    event = request.headers.get("X-GitHub-Event")
    payload = request.json

    if event == "push":
        return handle_push(payload)
    elif event == "pull_request":
        return handle_pull_request(payload)
    else:
        return jsonify({"status": "ignored", "event": event}), 200

# Errors Page
@app.route("/errors", methods=["GET"])
def get_errors():
    return jsonify(errors)

# Run Flask
if __name__ == "__main__":
    logging.info("Starting Flask GitHub App Listener on port 5000")
    app.run(port=5000, debug=True)
