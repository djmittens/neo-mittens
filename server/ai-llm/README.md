# AI/LLM Server

Local LLM inference using the 3080 Ti GPU.

## Options to consider:
- **Ollama** - Easy local LLM management
- **vLLM** - High-performance inference
- **text-generation-webui** - Web interface for various models
- **LocalAI** - OpenAI-compatible API

## Hardware:
- GPU: 3080 Ti (12GB VRAM)
- Good for models up to ~13B parameters

## Recommended Models:
- **Qwen 2.5 7B** - Great general purpose
- **DeepSeek Coder 6.7B** - Excellent for coding
- **Mistral 7B** - Fast and capable
- **Llama 3.1 8B** - Latest Meta model

## Installation

```bash
./install.sh
```

## Access

Once running, API will be available at:
- Local: http://localhost:11434 (Ollama default)
- Tailscale: http://[tailscale-ip]:11434
