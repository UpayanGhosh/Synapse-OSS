# Synapse — Complete Architecture Explainer
### Interview Preparation Guide for GenAI / Agentic AI Developer Roles

> **How to use this document:** Read it top to bottom once before your interview. Then use the section headers as a mental checklist. Every technical term in here is explained — you should be able to say it out loud in plain English AND use the correct buzzword in the same breath. That combination is what impresses interviewers.

> **Repo:** `D:\Shreya\Synapse-OSS` | **Branch:** main | **Lines:** 15,000+ Python | **Tests:** 302 passing

---

## Table of Contents

1. [What Is Synapse — The Big Picture](#1-what-is-synapse--the-big-picture)
2. [The 11 Subsystems and How They Connect](#2-the-11-subsystems-and-how-they-connect)
3. [End-to-End Request Flow](#3-end-to-end-request-flow)
4. [Async Gateway Pipeline](#4-async-gateway-pipeline)
5. [Channel Abstraction Layer](#5-channel-abstraction-layer)
6. [Hybrid Memory and RAG Engine](#6-hybrid-memory-and-rag-engine)
7. [LLM Router — Mixture of Agents](#7-llm-router--mixture-of-agents)
8. [Soul-Brain Sync (SBS) — Deep Dive](#8-soul-brain-sync-sbs--deep-dive)
9. [Dual Cognition Engine — Deep Dive](#9-dual-cognition-engine--deep-dive)
10. [Sentinel File Governance](#10-sentinel-file-governance)
11. [Supporting Systems](#11-supporting-systems)
12. [Technical Stack and Design Decisions](#12-technical-stack-and-design-decisions)
13. [Interview Cheat Sheet](#13-interview-cheat-sheet)

---

<!-- SECTIONS WRITTEN BELOW BY AI AGENTS — DO NOT EDIT ABOVE THIS LINE -->

