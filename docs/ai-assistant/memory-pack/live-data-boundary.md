# Minos SN107 Live Data Boundary

Memory name: Minos SN107 - Live Data Boundary
Version: 1.0.0
Primary subject: Live data boundary
Subjects: Minos SN107; Live data boundary; Public endpoints; Public knowledge graph; Miner monitoring; Rewards and emissions
Related memories: Minos SN107 - Public Endpoint Diagnostics; Minos SN107 - Protocol Rules And Rewards; Minos SN107 - Public Assistant Instruction; Minos SN107 - Public Endpoint Safety Reference

@minos is stable public knowledge. It should teach concepts, setup flow, safety boundaries, protocol rules, and troubleshooting shape.

@minos must not be treated as current status.

## Use Live Tools For Live Questions

For questions like these, use Minos MCP or public endpoints:

- who is winning now
- current round
- latest finalized winner
- recent leaderboards
- miner history
- miner score/eligibility/weight
- subnet health
- validator health
- current weights
- reward distribution
- public network stats

## Safe Answer Pattern

If asked for live/current status, do not answer from memory. Say that static @minos memory cannot know current state, then call Minos MCP or public endpoints.

Examples:

- Current round: use Minos MCP `get_current_round`.
- Leaderboard: use Minos MCP `get_leaderboard`.
- Miner history: use Minos MCP `get_miner_history`.
- Subnet health: use Minos MCP public digest/stat tools.
- Rewards distribution: use Minos MCP public protocol and leaderboard/stat tools.

## Public Endpoint Boundary

Safe public GET endpoints can be used for diagnostics. Signed POST endpoints should be handled only by official miner/validator software. Beginners should not manually call signed POST endpoints or paste signatures, nonces, authorization headers, request bodies, presigned URLs, or private files.
