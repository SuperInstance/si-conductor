# ⚡ Conductor

*Agent routing layer for multi-agent systems*

![⚡ Conductor](docs/images/conductor.jpg)

## What It Is

The Conductor is the routing layer that decides which agents interact with each visitor. It analyzes intent, recruits the right specialists from a pool, tracks engagement, and escalates to heavier models when confidence drops.

Not a controller. Not a boss. A bandleader — setting the tempo, recruiting the right players, and letting emergence happen.

## Install

```bash
pip install superinstance-conductor
```

## Features

- Dynamic agent recruitment based on visitor intent
- Engagement tracking with escalation thresholds
- 7 built-in agent profiles (or define your own)
- Session state management with per-visitor vectors
- Works with any LLM backend — Ollama, OpenAI, DeepSeek, anything

## Quick Start

```python
from superinstance import conductor

# See docs/api/conductor-api.md for full documentation
```

## Use It For

**Customer service bot swarm that routes questions to the right specialist**

Or anything else. This module is independently useful and Apache-2.0 licensed. Grow it for your industry. Send improvements back.

---

*Part of [LucidDreamer.AI](https://github.com/SuperInstance/luciddreamer-prototype) — built by [SuperInstance](https://github.com/SuperInstance).*
