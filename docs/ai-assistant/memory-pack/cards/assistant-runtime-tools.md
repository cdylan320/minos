# Minos SN107: Assistant Runtime Tools

Memory name: Minos SN107 - Assistant Runtime Tools
Version: 1.0.0
Primary subject: Assistant runtimes
Subjects: Assistant runtimes; Ditto; OpenClaw; Hermes; Public knowledge graph; Minos MCP; Safe support behavior
Related memories: Minos SN107 - Public Assistant Instruction; Minos SN107 - Live Data Boundary; Minos SN107 - Miner Quickstart; Minos SN107 - Safe Paste-Back Template; Minos SN107 - Public Endpoint Diagnostics

Minos can use Ditto, Minos MCP, OpenClaw, and Hermes together so miners get Minos-specific help from a local runtime.

Ditto provides the shared public `@minos` knowledge graph. The default path is a read-only subscription to `@minos`; local fallback seeding is only for cases where graph retrieval cannot be verified or is explicitly requested.

Minos MCP provides live public subnet data at `https://mcp.theminos.ai`. It is the correct source for current round, leaderboard, recent rounds, miner history, subnet overview, incentives, and emissions. Ditto should explain what live results mean, not replace live data.

OpenClaw and Hermes are optional local agent runtimes. They can use the Minos skill, Ditto skill, and Minos MCP connection so a miner can ask Minos-specific questions while working on the same machine.

MinosVM should install the pieces needed for Ditto, Minos MCP, and optional agent runtimes, then let the user choose whether to enable OpenClaw, Hermes, or no local assistant.

The setup must not upload `.env`, wallet files, miner configs, model provider keys, SSH keys, logs, presigned URLs, request signatures, active nonces, private validator data, or production infrastructure details.

If graph subscription or search cannot be verified, fallback seeding may save only public memory-pack files. The public graph remains the preferred source.
