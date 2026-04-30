import hashlib
import os
import re
import subprocess
from datetime import datetime
import ollama

# Models per role — matches thesis proposal
CODE_GEN_MODEL  = "qwen2.5-coder:latest"
CRITIC_MODEL    = "gemma2:latest"
ACTOR_MODEL     = "gemma2:latest"

TASK_PROMPT = (
    "Write an Ansible playbook to install kubeadm on a fresh Ubuntu Server. "
    "Use ansible_distribution_release for any apt repository entries — do NOT use "
    "shell substitutions like $(lsb_release -cs). "
    "Output ONLY raw yaml. Do not use markdown code fences or backticks."
)

FILE_NAME    = "install_kubeadm.yml"
VM           = "masters@192.168.122.48"
SSH_KEY      = ".ssh_keys/masters_id"
SSH_OPTS     = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
MAX_ATTEMPTS = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_yaml(text: str) -> str:
    cleaned = text.strip()
    fenced = re.search(r"```(?:yaml|yml)?\s*\n([\s\S]*?)\n```", cleaned, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip() + "\n"
    cleaned = re.sub(r"^```(?:yaml|yml)?\s*\n", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)
    return cleaned.strip() + "\n"


def scp_to_vm(local_path: str):
    subprocess.run(
        ["scp"] + SSH_OPTS + ["-i", SSH_KEY, local_path, f"{VM}:~/"],
        check=True, timeout=30,
    )


def make_run_dir(prompt: str) -> str:
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    run_dir = datetime.now().strftime(f"qwen_run_%Y%m%d_%H%M%S_%f_{prompt_hash}")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "prompt.txt"), "w") as f:
        f.write(prompt)
    print(f"Tracking run in directory: {run_dir}")
    return run_dir


def save_attempt(attempt_dir: str, prompt: str, playbook: str, execution_output: str,
                 returncode: int, critique: str = "", refined_prompt: str = ""):
    os.makedirs(attempt_dir, exist_ok=True)
    with open(os.path.join(attempt_dir, "prompt.txt"), "w") as f:
        f.write(prompt)
    with open(os.path.join(attempt_dir, FILE_NAME), "w") as f:
        f.write(playbook)
    with open(os.path.join(attempt_dir, "result.txt"), "w") as f:
        f.write(f"=== stdout ===\n{execution_output}\n\n=== returncode ===\n{returncode}\n")
    if critique:
        with open(os.path.join(attempt_dir, "critique.txt"), "w") as f:
            f.write(critique)
    if refined_prompt:
        with open(os.path.join(attempt_dir, "refined_prompt.txt"), "w") as f:
            f.write(refined_prompt)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def code_generator(task_prompt: str, history: list[dict] | None = None) -> str:
    """Generates or regenerates an Ansible playbook from the task prompt."""
    print(f"  [CodeGen / {CODE_GEN_MODEL}] Generating playbook...")
    messages = [{"role": "user", "content": task_prompt}]
    if history:
        messages = history
    response = ollama.chat(model=CODE_GEN_MODEL, messages=messages)
    return normalize_yaml(response.message.content)


def critic(playbook: str, execution_output: str, returncode: int) -> str:
    """Evaluates the playbook and execution result; returns structured feedback."""
    print(f"  [Critic / {CRITIC_MODEL}] Evaluating result...")
    prompt = (
        f"You are an Ansible expert reviewing a failed playbook.\n\n"
        f"=== Playbook ===\n{playbook}\n\n"
        f"=== Execution Output ===\n{execution_output}\n\n"
        f"=== Return Code ===\n{returncode}\n\n"
        "Identify the root cause of the failure. "
        "Be specific: name the failing task, the exact error, and the correct fix. "
        "Do not rewrite the playbook — only describe what needs to change and why."
    )
    response = ollama.chat(model=CRITIC_MODEL, messages=[{"role": "user", "content": prompt}])
    return response.message.content


def actor(task_prompt: str, critique_text: str) -> str:
    """Re-engineers the prompt based on the critic's feedback."""
    print(f"  [Actor / {ACTOR_MODEL}] Re-engineering prompt...")
    messages = [
        {"role": "user", "content": (
            f"You are re-engineering an IaC generation prompt to fix a failure.\n\n"
            f"=== Original Prompt ===\n{task_prompt}\n\n"
            f"=== Expert Critique ===\n{critique_text}\n\n"
            "Rewrite the prompt so that a code generator will avoid the identified failure. "
            "Add explicit constraints, corrections, or clarifications where needed. "
            "Keep all original intent. Output ONLY the rewritten prompt, nothing else."
        )},
    ]
    response = ollama.chat(model=ACTOR_MODEL, messages=messages)
    return response.message.content.strip()


def executor(playbook: str) -> tuple[str, int]:
    """Uploads and runs the playbook on the VM; returns (output, returncode)."""
    print(f"  [Executor] Uploading and running {FILE_NAME}...")
    with open(FILE_NAME, "w") as f:
        f.write(playbook)
    scp_to_vm(FILE_NAME)

    proc = subprocess.Popen(
        ["ssh"] + SSH_OPTS + ["-i", SSH_KEY, VM,
         f"ansible-playbook -i localhost, -c local ~/{FILE_NAME}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    output = ""
    for line in proc.stdout:
        print(line, end="", flush=True)
        output += line
    proc.wait()
    return output, proc.returncode


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def orchestrate(task_prompt: str, max_attempts: int = MAX_ATTEMPTS):
    run_dir = make_run_dir(task_prompt)
    current_prompt = task_prompt
    current_playbook = code_generator(current_prompt)

    for attempt in range(1, max_attempts + 1):
        print(f"\n=== Attempt {attempt}/{max_attempts} ===")
        attempt_dir = os.path.join(run_dir, f"attempt_{attempt}")

        execution_output, returncode = executor(current_playbook)
        no_hosts = "no hosts matched" in execution_output.lower()
        success = returncode == 0 and not no_hosts

        if success:
            save_attempt(attempt_dir, current_prompt, current_playbook, execution_output, returncode)
            print(f"\nPlaybook executed successfully on attempt {attempt}.")
            break

        # Critic diagnoses the failure
        critique_text = critic(current_playbook, execution_output, returncode)
        print(f"\n  [Critique]:\n{critique_text}\n")

        # Actor re-engineers the prompt
        refined_prompt = actor(current_prompt, critique_text)
        print(f"\n  [Refined Prompt]:\n{refined_prompt}\n")

        save_attempt(attempt_dir, current_prompt, current_playbook, execution_output,
                     returncode, critique=critique_text, refined_prompt=refined_prompt)
        print(f"Saved attempt to {attempt_dir}/")

        if refined_prompt.strip() == current_prompt.strip():
            print("Actor returned unchanged prompt. Stopping loop.")
            break

        # Feed refined prompt back into CodeGenerator
        current_prompt = refined_prompt
        current_playbook = code_generator(current_prompt)
    else:
        print(f"Reached maximum of {max_attempts} attempts without success.")

    print(f"\nRun saved to {run_dir}/")


if __name__ == "__main__":
    orchestrate(TASK_PROMPT)
