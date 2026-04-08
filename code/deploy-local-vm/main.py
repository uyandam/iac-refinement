# Main loop to run queries against VMs
import hashlib
import os
import re
import subprocess
from datetime import datetime
import anthropic
from dotenv import load_dotenv

# 1. Load the secret API key
load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

print("Code to generate IaC Code using AI Models")

my_prompt = "Write an Ansible playbook to install kubeadm on a fresh Ubuntu Server. Output ONLY raw yaml. Do not use markdown code fences or backticks."


def normalize_yaml_response(text: str) -> str:
    """Strip markdown wrappers so the saved file is valid raw YAML."""
    cleaned = text.strip()
    fenced_block = re.search(r"```(?:yaml|yml)?\s*\n([\s\S]*?)\n```", cleaned, re.IGNORECASE)
    if fenced_block:
        return fenced_block.group(1).strip() + "\n"

    cleaned = re.sub(r"^```(?:yaml|yml)?\s*\n", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)
    return cleaned.strip() + "\n"

message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": my_prompt}]
)

try:
    print("try block")
    file_name = "install_kubeadm.yml"

    iac_code = normalize_yaml_response(message.content[0].text)

    with open(file_name, "w") as f:
        f.write(iac_code)

    # Copy generated playbook to the target VM.
    subprocess.run(
        [
            "scp",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-i",
            ".ssh_keys/masters_id",
            file_name,
            "masters@192.168.122.48:~/",
        ],
        check=True,
        timeout=30,
    )
    
    print(f"Copied {file_name} to masters@192.168.122.48")

    # Create a timestamped run directory to track all iterations.
    prompt_hash = hashlib.sha256(my_prompt.encode()).hexdigest()[:8]
    run_dir = datetime.now().strftime(f"run_%Y%m%d_%H%M%S_%f_{prompt_hash}")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "prompt.txt"), "w") as f:
        f.write(my_prompt)
    print(f"Tracking run in directory: {run_dir}")

    current_code = iac_code
    for attempt in range(1, 6):
        print(f"Execution attempt {attempt}/5...")

        # Create a per-attempt subdirectory.
        attempt_dir = os.path.join(run_dir, f"attempt_{attempt}")
        os.makedirs(attempt_dir, exist_ok=True)

        # Execute the playbook on the target VM (stream output live).
        proc = subprocess.Popen(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                "-i",
                ".ssh_keys/masters_id",
                "masters@192.168.122.48",
                f"ansible-playbook -i localhost, -c local ~/{file_name}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        execution_output = ""
        for line in proc.stdout:
            print(line, end="", flush=True)
            execution_output += line
        proc.wait()

        class _Result:
            returncode = proc.returncode
            stdout = execution_output
            stderr = ""

        result = _Result()
        no_hosts_matched = "no hosts matched" in execution_output.lower()

        # Truncate stdout to the last 50 lines to avoid sending verbose task logs.
        stdout_tail = "\n".join(execution_output.splitlines()[-50:])

        # Save the prompt, playbook and execution result for this attempt.
        with open(os.path.join(attempt_dir, "prompt.txt"), "w") as f:
            f.write(my_prompt)
        with open(os.path.join(attempt_dir, file_name), "w") as f:
            f.write(current_code)
        with open(os.path.join(attempt_dir, "result.txt"), "w") as f:
            f.write(f"=== stdout ===\n{execution_output}\n\n=== stderr ===\n{result.stderr}\n\n=== returncode ===\n{result.returncode}\n")
        print(f"Saved playbook and result to {attempt_dir}/")

        # Exit loop early if the playbook ran successfully.
        if result.returncode == 0 and not no_hosts_matched:
            print(f"Playbook executed successfully on attempt {attempt}.")
            break

        print(f"Attempt {attempt} failed. Feeding output back to model for correction...")

        # Feed execution output back to the model for fine-tuning.
        # Prefer stderr when available (it contains the actual error); fall back to stdout tail.
        error_context = stdout_tail
        followup_message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[
                {"role": "user", "content": my_prompt},
                {"role": "assistant", "content": current_code},
                {
                    "role": "user",
                    "content": (
                        f"The playbook failed with the following output:\n\n{error_context}\n\n"
                        "Provide a corrected version of the playbook. "
                        "Output ONLY the yaml code, no explanations."
                    ),
                },
            ],
        )

        refined_code = normalize_yaml_response(followup_message.content[0].text)
        print("Model fine-tuning response received.")

        if refined_code.strip() and refined_code.strip() != current_code.strip():
            current_code = refined_code
            with open(file_name, "w") as f:
                f.write(current_code)
            with open(os.path.join(attempt_dir, "refined_playbook.yml"), "w") as f:
                f.write(current_code)
            print(f"Playbook refined and saved to {file_name}. Re-copying to VM...")
            subprocess.run(
                [
                    "scp",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=10",
                    "-i",
                    ".ssh_keys/masters_id",
                    file_name,
                    "masters@192.168.122.48:~/",
                ],
                check=True,
                timeout=30,
            )
        else:
            print("No changes suggested by the model. Stopping loop.")
            break
    else:
        print("Reached maximum of 5 attempts without a successful execution.")

except Exception as e:
    print(f"Error: {e}")