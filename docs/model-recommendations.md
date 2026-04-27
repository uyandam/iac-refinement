# Model Recommendations for Local Hardware

## Hardware Summary

| Component | Spec |
|---|---|
| CPU | AMD Ryzen 5 7600 — 6 cores / 12 threads |
| RAM | 32GB |
| GPU | AMD Raphael (integrated only — no discrete GPU) |
| Storage | ~907GB total |

All inference runs on CPU via Ollama / llama.cpp. No discrete GPU means 7B–9B Q4-quantized models are the practical sweet spot.

---

## Recommended Models

| Model | Ollama Tag | RAM (Q4) | Speed (est.) | Role in Framework |
|---|---|---|---|---|
| Qwen2.5-Coder 7B | `qwen2.5-coder` | ~4.5GB | 15–25 tok/s | Code Generator (primary) |
| Gemma 2 9B | `gemma2` | ~5.5GB | 12–20 tok/s | Actor + Critic |
| Gemma 4 4B | `gemma3:4b` | ~2.8GB | 25–35 tok/s | Fast baseline / Actor |
| LLaMA 3.1 8B | `llama3.1` | ~5GB | 15–20 tok/s | Comparison / ensemble |

All models should be run at **temperature = 0** for deterministic, reproducible outputs.

---

## Models to Avoid on This Hardware

| Model | Reason |
|---|---|
| Qwen2.5-Coder 32B | ~20GB RAM, 3–5 tok/s — too slow for iterative RL loops |
| LLaMA 3.1 70B | Exceeds available RAM |
| Any unquantized (fp16) 13B+ | RAM overhead too high |

---

## Practical Notes

- **32GB RAM** allows 2–3 models loaded simultaneously — useful for Actor, Critic, and Code Generator running as separate agents.
- **Episode timing:** at ~15 tok/s, a 500-token IaC generation takes ~30s. A 5-attempt RL episode is roughly 3–5 minutes. Keep early experiments scoped to Ansible playbooks.
- **No ROCm needed:** the integrated Raphael GPU technically supports ROCm but setup complexity outweighs marginal gains for this workload.
- **llama.cpp** can be used as an alternative to Ollama for finer control over quantization and threading.

---

## Install Commands

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull recommended models
ollama pull qwen2.5-coder
ollama pull gemma2
ollama pull gemma3:4b
ollama pull llama3.1
```
