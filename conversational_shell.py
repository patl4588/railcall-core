#!/usr/bin/env python3
import os
import sys
import json
import re
import subprocess

try:
    from groq import Groq
except ImportError:
    print("❌ ERROR: 'groq' package not installed. Run: pip3 install groq")
    sys.exit(1)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("❌ ERROR: GROQ_API_KEY environment variable not found. Please export it.")
    sys.exit(1)

client = Groq(api_key=GROQ_API_KEY)

# Load the local CSV to give Groq context
FIXTURE_PATH = "fixtures/access_logs.csv"
try:
    with open(FIXTURE_PATH, "r") as f:
        csv_data = f.read()
except FileNotFoundError:
    csv_data = "timestamp,ip_address,endpoint,threat_level\n2026-06-17T14:05Z,45.33.12.9,/api/login,low\n2026-06-17T14:15Z,185.199.108.153,/admin/db_dump,critical\n"

system_prompt = f"""You are the Railcall System Engine, an advanced developer assistant.
You are helping a developer build secure, airlocked dashboards.

You have access to this local CSV data on their machine:
---
{csv_data}
---

INSTRUCTIONS:
1. Converse naturally and professionally. Answer their questions about the data or just chat with them.
2. IMPORTANT: Do NOT output JSON unless the user explicitly asks you to build, compile, or create a workflow/dashboard.
3. When they DO ask to build/compile, you MUST output a JSON block wrapped in ```json ... ``` containing the filtered records.

JSON Format:
```json
{{
  "action": "compile_dashboard",
  "records": [
    {{ "timestamp": "...", "ip_address": "...", "endpoint": "...", "threat_level": "..." }}
  ]
}}
```
"""

messages = [{"role": "system", "content": system_prompt}]

print("\n\033[1;36m=================================================================\033[0m")
print("\033[1;36m 🧠 RAILCALL SYSTEM ENGINE (Powered by Groq Llama-3.1)\033[0m")
print("\033[1;36m=================================================================\033[0m")
print(" Local context loaded: " + FIXTURE_PATH + "\n")

# A simulated multi-turn conversation
simulated_conversation = [
    "Hi system, how are you?",
    "Can you look at my access logs and tell me what you see?",
    "I want some work flows. Filter out the low threats and build the dashboard for me."
]

for turn, user_input in enumerate(simulated_conversation, 1):
    print(f"\033[1;32m🧑 You (Turn {turn}):\033[0m {user_input}")
    messages.append({"role": "user", "content": user_input})
    
    print("\033[1;30m🤖 System is reasoning...\033[0m", end="\r")
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.3
        )
        
        response = completion.choices[0].message.content
        messages.append({"role": "assistant", "content": response})
        
        sys.stdout.write("\033[K") # clear the reasoning line
        print(f"\033[1;35m🤖 System:\033[0m\n{response}\n")

        # Check if the System decided to output the JSON build command
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
        if json_match:
            payload = json.loads(json_match.group(1))
            if payload.get("action") == "compile_dashboard":
                print("\033[1;33m⚡ [INTERNAL ROUTER] System triggered a build! Valid JSON intercepted. Passing to local builder...\033[0m")
                
                with open(".temp_compile.json", "w") as f:
                    json.dump(payload["records"], f)
                
                builder_code = """
import json, sys, os

with open(".temp_compile.json", "r") as f:
    records = json.load(f)

rows_html = ""
for row in records:
    badge = "crit" if row.get('threat_level', '').lower() == 'critical' else "warn"
    rows_html += f'''
        <tr>
          <td class="mono dim">{row.get('timestamp', '')}</td>
          <td class="mono">{row.get('ip_address', '')}</td>
          <td class="dim">{row.get('endpoint', '')}</td>
          <td class="right"><span class="lvl {badge}">{row.get('threat_level', '')}</span></td>
        </tr>'''

html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Railcall | Airlocked Security Grid</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0a0a0a; color:#e5e7eb; padding:2rem;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:64rem; margin:0 auto; }}
  .head {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:2rem; }}
  h1 {{ font-size:1.5rem; font-weight:600; color:#fff; letter-spacing:-0.01em; margin:0; }}
  .sub {{ font-size:0.875rem; color:#9ca3af; margin-top:0.25rem; }}
  .secure {{ padding:0.25rem 0.75rem; background:rgba(20,83,45,0.3); color:#4ade80;
             border:1px solid #166534; border-radius:9999px; font-size:0.75rem;
             font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
  .card {{ background:#171717; border:1px solid #262626; border-radius:0.75rem;
           overflow:hidden; box-shadow:0 25px 50px -12px rgba(0,0,0,0.6); }}
  table {{ width:100%; border-collapse:collapse; font-size:0.875rem; text-align:left; }}
  thead th {{ font-size:0.7rem; color:#9ca3af; text-transform:uppercase; letter-spacing:0.05em;
              background:rgba(0,0,0,0.2); border-bottom:1px solid #262626; padding:1rem 1.5rem; font-weight:500; }}
  tbody td {{ padding:1rem 1.5rem; border-top:1px solid #262626; }}
  tbody tr:hover {{ background:rgba(255,255,255,0.05); }}
  .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
  .dim {{ color:#9ca3af; }} .right {{ text-align:right; }}
  .lvl {{ padding:0.2rem 0.6rem; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em;
          border:1px solid; border-radius:0.375rem; font-family:ui-monospace,Menlo,monospace; }}
  .crit {{ background:rgba(127,29,29,0.4); color:#f87171; border-color:#991b1b; }}
  .warn {{ background:rgba(120,53,15,0.4); color:#fbbf24; border-color:#92400e; }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <div>
        <h1>Active Threat Ledger</h1>
        <p class="sub">Compiled via Railcall Local Loopback — this page makes 0 external requests (no CDN, fully self-contained)</p>
      </div>
      <div class="secure">Airlock: SECURE</div>
    </div>
    <div class="card">
      <table>
        <thead>
          <tr><th>Timestamp</th><th>IP Address</th><th>Endpoint</th><th class="right">Threat Level</th></tr>
        </thead>
        <tbody>{rows_html}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
'''
with open("railcall_dashboard.html", "w") as f:
    f.write(html_content)

print("\\033[1;32m✅ SUCCESS: Dashboard physically built -> railcall_dashboard.html\\033[0m")
"""
                with open(".temp_builder.py", "w") as f:
                    f.write(builder_code)
                
                subprocess.run(["python3", ".temp_builder.py"])
                
                # Cleanup
                os.remove(".temp_compile.json")
                os.remove(".temp_builder.py")

    except Exception as e:
        sys.stdout.write("\033[K")
        print(f"\033[1;31m❌ ERROR:\033[0m {str(e)}\n")

print("\nProcess finished.")