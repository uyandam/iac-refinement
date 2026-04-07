import os
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# The Error you just got
error_msg = "FAILED! => {'msg': 'The task includes an option with an undefined variable. The error was: {{ ansible_user }}: ansible_user is undefined'}"

# Read the original broken file
with open("install_microk8s.yml", "r") as f:
    original_code = f.read()

prompt = f"""
The following Ansible playbook failed with this error: {error_msg}

Original Code:
{original_code}

Please fix the undefined variable error. Note that I am running this locally on the VM. 
Output ONLY the corrected YAML code.
"""

print("🔄 Asking Claude to fix the error...")

message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=2000,
    messages=[{"role": "user", "content": prompt}]
)

# Clean and save the fixed version
clean_code = message.content.text.replace("```yaml", "").replace("```", "").strip()
with open("install_microk8s_v2.yml", "w") as f:
    f.write(clean_code)

print("✅ Fixed version saved as install_microk8s_v2.yml")
