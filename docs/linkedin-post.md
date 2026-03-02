# LinkedIn Post Draft

## Post-Ready (Long)

I just completed **VulnSentinel AI**: a plug-and-play, open-source vulnerability pipeline for container images.

This was built under the guidance and mentorship of **Sanket**.

I wanted to build something practical: not a demo that looks good for one day, but a workflow teams can actually run, understand, and extend.

What it does right now:

- emits scan jobs into RabbitMQ
- generates and reuses SBOMs with Syft
- scans vulnerabilities with Grype
- applies runtime-context/VEX-style logic to reduce noisy findings
- stores metadata in PostgreSQL and artifacts in RustFS
- visualizes scan outcomes in Grafana
- autoscales worker pods with KEDA based on queue depth

I validated autoscaling with burst tests (50-message runs): workers scaled up under load and scaled down after queue drain.

Tech stack:

- Python
- Kubernetes (kind), KEDA
- RabbitMQ, PostgreSQL, RustFS, Grafana
- Syft, Grype
- Docker, Docker Compose
- Codex + Gemini CLI for development workflow
- NotebookLM for project video generation support

Development workflow:

I used a spec-driven engineering approach (requirements first, implementation second), plus AI-assisted iteration for faster refactoring, validation scripting, and documentation quality.

Why this matters:

Security pipelines should not always require expensive platform licensing just to get started.
This project is meant to stay **free and open source**, so teams can run it, inspect it, and customize it for their own environment.

The architecture direction is inspired by enterprise cloud security operating patterns (including Prisma/Palo Alto style approaches), but implemented as an open and adaptable stack.

Practical local-first detail:

Even if Kubernetes is down, teams can still spin up Docker Compose services like Grafana/Postgres and inspect persisted local data.

What I am sharing with this post:

- architecture diagram
- autoscaling animation
- CLI walkthrough video

GitHub: **<ADD_YOUR_GITHUB_REPO_URL_HERE>**

If you want to test this in your environment or collaborate, message me.

## Post-Ready (Short)

Built **VulnSentinel AI**: an open-source, plug-and-play container vulnerability pipeline.

Under Sanket's mentorship, I implemented:

- RabbitMQ -> KEDA-autoscaled workers -> PostgreSQL/RustFS -> Grafana
- SBOM + vulnerability scan + context-aware VEX-style logic
- burst-load autoscaling validation (50 messages)

Built with a spec-driven workflow using Codex + Gemini CLI, and NotebookLM for project video support.

Goal: make strong security pipeline foundations more accessible, customizable, and affordable.

GitHub: **<ADD_YOUR_GITHUB_REPO_URL_HERE>**

## Suggested Hashtags

`#OpenSource #Kubernetes #KEDA #DevSecOps #CloudSecurity #ContainerSecurity #PostgreSQL #Grafana #RabbitMQ #PlatformEngineering`
