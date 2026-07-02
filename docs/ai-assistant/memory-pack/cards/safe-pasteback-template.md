# Minos SN107: Safe Paste-Back Template

Memory name: Minos SN107 - Safe Paste-Back Template
Version: 1.0.0
Primary subject: Safe paste-back
Subjects: Safe paste-back; Safe support behavior; Endpoint safety; Troubleshooting; Validator safety
Related memories: Minos SN107 - Public Assistant Instruction; Minos SN107 - Public Endpoint Safety Reference; Minos SN107 - Troubleshooting Playbook; Minos SN107 - Validator Safety

When asking a miner or validator for diagnostic information, request only public-safe data.

Safe to paste:

- public hotkey
- public UID
- selected tool name
- whether demo mode passes
- redacted command output
- redacted error message
- public endpoint output
- PM2 status without secrets
- Docker version or status

Do not paste:

- seed phrase
- private key
- `.env`
- API key
- SSH key
- wallet file
- private miner config
- private validator config
- raw private logs
- presigned URL
- request signature
- active nonce
- authorization header
- truth file
- private BAM or VCF
- database/admin output

If a user already pasted sensitive material, tell them to rotate or revoke the affected secret and remove the message wherever possible.
