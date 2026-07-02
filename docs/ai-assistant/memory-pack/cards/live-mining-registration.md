# Minos SN107: Live Mining And Registration

Memory name: Minos SN107 - Live Mining And Registration
Version: 1.0.0
Primary subject: Live mining
Subjects: Live mining; Bittensor wallet and hotkey; Miner onboarding; Eligibility and weight; Public endpoints; Safe support behavior
Related memories: Minos SN107 - Miner Lifecycle; Minos SN107 - Rewards Eligibility And Weight; Minos SN107 - Public Endpoint Diagnostics; Minos SN107 - Safe Paste-Back Template

Live Minos mining requires the official miner software, a Bittensor wallet, a hotkey, and correct subnet registration.

Useful public concepts:

- A wallet is the local Bittensor identity container.
- A hotkey is the miner identity used on the subnet.
- A UID is the subnet assignment for a registered hotkey.
- Registration is required before a miner can receive live subnet weight.
- A miner can run locally but still have 0 weight if it is not registered, not submitting, not scoring, or not eligible yet.

Never ask a user to paste seed phrases, private keys, wallet files, `.env`, or raw credentials. Public support should ask for public hotkeys, public UIDs, public endpoint output, and redacted logs only.

For current registration, UID, score, eligibility, weight, and emissions, use Minos MCP or public endpoints.
