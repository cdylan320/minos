# Minos SN107: PM2 And Docker Runtime

Memory name: Minos SN107 - PM2 And Docker Runtime
Version: 1.0.0
Primary subject: Runtime operations
Subjects: Runtime operations; PM2 supervision; Docker runtime; Miner monitoring; Troubleshooting; Hardware requirements
Related memories: Minos SN107 - Hardware And Runtime Guide; Minos SN107 - Miner Lifecycle; Minos SN107 - Demo Mode; Minos SN107 - Troubleshooting Playbook

Minos miners rely on Docker for variant-calling workloads and may use PM2 to keep miner processes running.

Docker checks are useful when the miner cannot start a job, cannot produce output, or fails during tool execution.

PM2 checks are useful for process supervision. Common public-safe commands include listing processes, checking status, and reading redacted logs.

Important distinction:

- PM2 online means the process is running.
- Docker available means containers can run.
- Neither one proves that live submissions are accepted, scored, eligible, weighted, or earning.

Good support order:

1. Confirm Docker works.
2. Confirm demo mode completes.
3. Confirm the miner process is running.
4. Confirm live registration and public scoring state.
5. Tune only after valid scored live rounds exist.

Do not paste private configs, provider keys, wallet data, presigned URLs, request signatures, active nonces, or raw private logs.
