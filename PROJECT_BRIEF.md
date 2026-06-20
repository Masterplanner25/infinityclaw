# Project Brief — Infinity Claw

## Vision

Infinity Claw is an AI-native personal workspace and agent platform. It gives agents structured access to human knowledge — files, memory, tasks, relationships — and gives humans precise control over what agents can see, remember, and do.

It is the first concrete application in the **Masterplan Infinite Weave**: a framework for building interconnected agentic systems on the Nodus Language Ecosystem and the AINDY execution kernel.

---

## Problem Statement

AI assistants today are stateless, context-blind, and isolated from real work:

- They forget everything between sessions unless you feed it back manually
- They have no access to your files, project history, or domain knowledge
- They cannot coordinate across tasks or hand off to other agents
- They live inside closed cloud platforms with opaque data handling

The result is that every conversation starts from zero, and the assistant is only as useful as what you happen to paste in.

---

## What Infinity Claw Does Differently

Infinity Claw is not a chat interface bolted on top of an LLM.

It is a **workspace that agents operate inside**. The workspace holds structured knowledge — documents, memories, assets, tasks. Agents are spawned against a workspace and given controlled access to its contents. Every turn is grounded in context the agent already possesses; memory persists; knowledge accumulates.

The platform is:

- **Self-hosted** — you run it, you own the data
- **Multi-channel** — agents reachable from WebChat, Telegram, Discord, Slack, Matrix, Signal
- **Multi-agent** — multiple specialized agents within a single gateway
- **Observable** — every turn, every memory write, every cron job tracked through AINDY lifecycle events

---

## Target Users

**Primary:** Developers and technical power users who want a self-hosted AI assistant they can extend, instrument, and trust.

**Secondary:** Researchers, writers, and operators who need persistent AI context without sending their work to a third-party SaaS.

**Future:** Teams using Infinity Claw as the execution layer for multi-agent pipelines within the Masterplan Infinite Weave.

---

## Success Criteria

1. A single `claw start` gives you a working AI workspace from a config file and an API key
2. Agents remember relevant context across sessions without manual prompting
3. Files and documents in a workspace become agent-accessible knowledge
4. Any channel (Telegram, Discord, etc.) reaches the same persistent agent
5. Adding a new agent, channel, or skill requires no code changes
6. AINDY platform integration is seamless — Claw runs standalone or mounted inside a larger Infinite Weave deployment

---

## Non-Goals

- **Not a filesystem replacement.** Infinity Claw organizes knowledge for agent access; it does not replace a filesystem or cloud storage
- **Not an IDE.** Code execution and editing are tools agents can invoke; Claw is not itself a development environment
- **Not a general-purpose orchestration runtime.** That is Nodus and AINDY. Claw is an application built on top of those runtimes
- **Not a multi-tenant SaaS.** Single-operator deployment; multi-user access is controlled by the operator, not the platform
- **Not a chatbot.** Agents in Claw are goal-directed, context-aware, and workspace-grounded — not reactive reply generators
