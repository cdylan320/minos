# Minos SN107: What Minos Is

Memory name: Minos SN107 - What Minos Is
Version: 1.0.0
Primary subject: Minos SN107
Subjects: Minos SN107; Public knowledge graph; Miner onboarding; Validators; Protocol rules
Related memories: Minos SN107 - Miner Lifecycle; Minos SN107 - Validator Basics; Minos SN107 - Protocol Rules And Rewards; Minos SN107 - Live Data Boundary

Minos is Bittensor subnet 107 for genomic variant calling.

Miners run supported variant-calling tools on challenge genomic data and submit their configuration or pipeline through the official miner software. Validators rerun miner submissions, generate calls, compare them against validator-side benchmark truth data, and assign scores and weights through subnet rules.

Minos is not a generic benchmark where miners manually paste finished VCF output into public support. The public support path is:

1. install the official miner
2. verify Docker and dependencies
3. run demo mode
4. register the miner hotkey
5. submit through the official miner software
6. inspect public score, eligibility, weight, and history
7. tune carefully only after the miner has valid scored rounds

The `@minos` knowledge graph is stable public memory. It explains concepts, setup, troubleshooting, scoring, safety, and public operational guidance. For current rounds, current weights, current winners, live miner status, or live validator status, use Minos MCP or public Minos endpoints instead of static memory.
