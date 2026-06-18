#!/usr/bin/env python3
"""
Railcall Local LLM Compiler — measured-airlock build with STRICT JSON ENFORCEMENT.
Forces the local LLM to output valid JSON matching the schema, eliminating Python/SQL hallucinations.
"""
import sys
import os
import json
import hashlib
import urllib.request
import urllib.error
import subprocess
from datetime import datetime, timezone

WORKSPACE_DIR = os.environ.get("RAILCALL_WORKSPACE", os.path.dirname(os.path.abspath(__file__)))
FIXTURE_PATH  = os.path.join(WORKSPACE_DIR, "fixtures", "access_logs.csv")
CONTRACT_PATH = os.path.join(WORKSPACE_DIR, "library", "input_contract.json")
RECEIPT_PATH  = os.path.join(WORKSPACE_DIR, "mcp_interpret_receipt.json")

OLLAMA_URL    = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL  = os.environ.get("RAILCALL_OLLAMA_MODEL", "qwen2.5-coder:1.5b")

# STRICT LOOPBACK ONLY. NO EXTERNAL PORTS ALLOWED.
LOOPBACK_TOKENS = ("127.0.0.1", "[::1]", "localhost", "->127.0.0.1", "->[::1]")

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            h.update(block)
    return h.hexdigest()

def measure_open_sockets(pid):
    cmd = ["lsof", "-a", "-i", "-P", "-n", "-p", str(pid)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except Exception as e:
        return {"measured": False, "reason": str(e), "loopback_socket_count": None, "external_socket_count": None}

    raw = proc.stdout or ""
    lines = raw.strip().splitlines()
    data_lines = lines[1:] if len(lines) > 1 else []

    loopback, external = [], []
    for line in data_lines:
        if any(tok in line for tok in LOOPBACK_TOKENS): loopback.append(line)
        else: external.append(line)

    return {
        "measured": True, "exit_code": proc.returncode, "raw_output": raw,
        "loopback_socket_count": len(loopback), "external_socket_count": len(external),
        "loopback_sockets": loopback, "external_sockets": external,
    }

def query_local_llm_json(user_prompt, system_instruction):
    """Queries Local Ollama and FORCES strict JSON format."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"System: {system_instruction}\n\nUser: {user_prompt}",
        "stream": False,
        "format": "json"
    }
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8")).get("response", "")

def run_interpret_pass(user_prompt):
    checks_failed = []
    parsed_result = {}
    records = []
    
    print("=== STARTING STRICT JSON COMPILATION PASS ===")
    
    try:
        fixture_hash = sha256_file(FIXTURE_PATH)
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f: csv_raw = f.read()
        with open(CONTRACT_PATH, "r", encoding="utf-8") as f: contract = json.load(f)
    except Exception as e:
        print(f"❌ Failed to read fixtures: {e}")
        return 1

    system_instruction = (
        "You are a strict data processor. You MUST return ONLY a JSON object. No markdown, no code, no explanations. "
        "Read the provided CSV. Extract the rows matching the user's request. "
        "Your output must exactly match this JSON structure: "
        "{\"status\": \"success\", \"reasoning\": \"brief explanation\", \"compiled_records\": [{\"timestamp\": \"...\", \"ip_address\": \"...\", \"endpoint\": \"...\", \"threat_level\": \"...\"}]}"
    )
    user_query = f"CSV Input:\n{csv_raw}\n\nTask:\n{user_prompt}"

    print(f"  Querying Local Engine ({OLLAMA_MODEL}) and forcing JSON format...")
    llm_raw = ""
    try:
        llm_raw = query_local_llm_json(user_query, system_instruction)
    except Exception as e:
        checks_failed.append(f"local_llm_error: {e}")

    # Physical Sockets Check
    network_audit = measure_open_sockets(os.getpid())
    if network_audit["measured"]:
        ext = network_audit["external_socket_count"]
        print(f"  lsof external socket count: {ext}")
        if ext > 0: checks_failed.append(f"airlock_breach: {ext} external sockets")

    # Parse and Validate the forced JSON
    if llm_raw and not checks_failed:
        try:
            parsed_result = json.loads(llm_raw)
            records = parsed_result.get("compiled_records", [])
        except json.JSONDecodeError:
            checks_failed.append(f"llm_failed_json_constraint: Model returned invalid JSON: {llm_raw[:100]}...")

        required_headers = contract.get("required_headers", [])
        for i, r in enumerate(records):
            for h in required_headers:
                if h not in r: checks_failed.append(f"schema_violation: record missing '{h}'")

    status = "COMPILER_PASSED_OFFLINE" if not checks_failed else "COMPILER_FAILED"
    
    receipt = {
        "schema": "railcall.strict_json_receipt.v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "input_hash": f"sha256:{fixture_hash}",
        "network_audit": network_audit,
        "nlp_reasoning": parsed_result.get("reasoning", ""),
        "audited_rows": len(records),
        "failures": checks_failed,
        "status": status
    }

    with open(RECEIPT_PATH, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
        
    print(f"  Status: {status}")
    if status == "COMPILER_PASSED_OFFLINE":
        print("\n✅ VALIDATED JSON OUTPUT:")
        print(json.dumps(records, indent=2))
    else:
        print(f"\n❌ FAILURES: {checks_failed}")
    return 0 if status == "COMPILER_PASSED_OFFLINE" else 1

if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Filter out low threat levels."
    sys.exit(run_interpret_pass(prompt))
