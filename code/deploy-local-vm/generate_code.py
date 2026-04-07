import os
import anthropic
from dotenv import load_dotenv

# 1. Load the secret API key
load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# 2. Define the task
# We want Claude to write a playbook for your fresh Ubuntu VM
my_prompt = "Write an Ansible playbook to install MicroK8s on a fresh Ubuntu Server. Output ONLY the yaml code, no explanations."

print("🚀 Asking Claude to generate code...")

# 3. Call the API
try:
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": my_prompt}]
    )

    # 4. Save the output to a file
    iac_code = message.content[0].text
    with open("install_microk8s.yml", "w") as f:
        f.write(iac_code)
    
    print("✅ Success! Created install_microk8s.yml")

except Exception as e:
    print(f"❌ Error: {e}")
