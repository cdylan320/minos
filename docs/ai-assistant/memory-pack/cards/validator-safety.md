# Minos SN107: Validator Safety

Memory name: Minos SN107 - Validator Safety
Version: 1.0.0
Primary subject: Validator safety
Subjects: Validator safety; Validators; Safe support behavior; Safe paste-back; Endpoint safety; Live data boundary
Related memories: Minos SN107 - Validator Guide; Minos SN107 - Validator Basics; Minos SN107 - Safe Paste-Back Template; Minos SN107 - Public Assistant Instruction

Validator support must be stricter than miner support because validators touch benchmark and scoring materials.

Public-safe validator help can discuss:

- process state
- Docker availability
- public validator dashboard status
- redacted logs
- public repo commands
- high-level scoring concepts
- general hardware expectations

Never paste or request:

- seed phrases or private keys
- `.env` values
- private validator files
- truth VCFs
- confident-region files
- private benchmark data
- presigned URLs
- request signatures
- active nonces
- authorization headers
- database or admin output
- production infrastructure details

For current validator state, use Minos MCP or public endpoints when available. Static `@minos` memory should provide safe interpretation, not live claims.
