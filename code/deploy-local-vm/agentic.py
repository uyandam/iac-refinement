import os
import subprocess
import anthropic
from dotenv import load_dotenv
from pprint import pprint


load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# 1. Define the Tools (The "Hands" of the Agent)
def run_ssh_command(command: str):
    """Executes a command on the target VM via SSH and returns output."""
    print(f"  [Executing]: {command}")
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-i", ".ssh_keys/masters_id", 
             "masters@192.168.122.48", command],
            capture_output=True, text=True, timeout=60
        )
        return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    except Exception as e:
        return f"Execution Failed: {str(e)}"

def write_and_upload_playbook(filename: str, content: str):
    """Writes a local YAML file and SCPs it to the VM."""
    print(f"  [Uploading]: {filename}")
    with open(filename, "w") as f:
        f.write(content)
    try:
        subprocess.run(
            ["scp", "-o", "StrictHostKeyChecking=no", "-i", ".ssh_keys/masters_id", 
             filename, "masters@192.168.122.48:~/"],
            check=True
        )
        return "File uploaded successfully."
    except Exception as e:
        return f"Upload failed: {str(e)}"

# 2. Tool Specification for Claude
tools = [
    {
        "name": "run_ssh_command",
        "description": "Run a shell command on the remote Ubuntu VM to check status or execute playbooks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The full shell command."}
            },
            "required": ["command"]
        }
    },
    {
        "name": "write_and_upload_playbook",
        "description": "Create an Ansible playbook locally and upload it to the remote VM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "content": {"type": "string", "description": "The raw YAML content."}
            },
            "required": ["filename", "content"]
        },
        "cache_control": {"type": "ephemeral"}  # Cache tools list — it never changes
    }
]

MAX_OUTPUT = 500   # max chars to keep from each tool result
HISTORY_WINDOW = 6 # number of messages to keep (must be even: assistant+user pairs)

# 3. The Orchestration Loop
def run_agent(prompt):
    messages = [{"role": "user", "content": prompt}]
    
    # Allow the agent up to 10 "thoughts" or "actions" to solve the problem
    for i in range(10):
        print(f"\n--- Agent Turn {i+1} ---")
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            tools=tools,
            messages=messages
        )

        # If Claude just wants to talk (no tools), we are done
        if response.stop_reason != "tool_use":
            print("Final Answer:", response.content[0].text)
            break

        # If Claude wants to use tools
        tool_results = []
        
        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if block.type == "tool_use":
                # Route the tool call to the actual Python function
                if block.name == "run_ssh_command":
                    out = run_ssh_command(block.input["command"])
                elif block.name == "write_and_upload_playbook":
                    out = write_and_upload_playbook(block.input["filename"], block.input["content"])
                
                # Truncate large outputs to avoid ballooning token usage
                if len(out) > MAX_OUTPUT:
                    out = out[:MAX_OUTPUT] + f"\n...[truncated, {len(out)} chars total]"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": out
                })

        # Add results back to history for the next turn
        messages.append({"role": "user", "content": tool_results})

        # Sliding window: keep the initial user prompt + last HISTORY_WINDOW messages
        if len(messages) > HISTORY_WINDOW + 1:
            messages = messages[:1] + messages[-(HISTORY_WINDOW):]

if __name__ == "__main__":
    run_agent("Install kubeadm on the remote VM. Check if it is already installed first. If it fails, investigate why and fix it.")