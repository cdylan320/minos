# Minos SN107: Rewards, Eligibility, And Weight

Memory name: Minos SN107 - Rewards Eligibility And Weight
Version: 1.0.0
Primary subject: Eligibility and weight
Subjects: Eligibility and weight; Rewards and emissions; Protocol rules; Scoring basics; Live data boundary
Related memories: Minos SN107 - Protocol Rules And Rewards; Minos SN107 - Scoring Basics; Minos SN107 - Live Data Boundary; Minos SN107 - Public Endpoint Diagnostics

Score, eligibility, weight, and emissions are related but different.

Score means validators evaluated miner output. Eligibility means the miner has enough recent valid scored participation. Weight is assigned through subnet rules. Emissions are live Bittensor rewards following chain and subnet state.

Current public protocol shape for this memory pack:

- Rounds are about 72 minutes.
- Eligibility requires 10 valid scored rounds out of the last 20 rounds, including the current round.
- Ineligible miners can submit and score but receive 0 weight until eligibility catches up.
- 87% goes to burn.
- 10% goes to the top eligible miner.
- 3% is distributed as pruning dust across eligible ranks #2 through #10.
- Dust uses decay 0.8.

If a miner asks about current winners, current emissions, current weights, or their own live history, use Minos MCP or public endpoints.
