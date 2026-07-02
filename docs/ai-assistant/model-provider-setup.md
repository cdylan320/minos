# Model Provider Setup For Minos Miner AI Assistant

Ditto gives OpenClaw or Hermes shared Minos memory through the public `@minos`
knowledge graph. The live launch graph is `Minos SN107 Public Knowledge Graph`
version `1.0.0`. If graph subscription or search cannot be verified, Minos can
save the same public memory-pack files into the agent's private Ditto memories
as a local fallback. Ditto does not provide the reasoning model for
those runtimes. Minos MCP provides live public subnet data from
`https://mcp.theminos.ai`. After Minos installs the graph
subscription/fallback, Minos MCP, and local skills, the miner still connects a
model provider in OpenClaw or Hermes.

## Recommended 1.0.0 Flow

1. Set up Minos.
2. Choose OpenClaw by default, or Hermes if preferred.
3. Subscribe Ditto to the public `@minos` knowledge graph, with private fallback seeding from public docs only if graph access cannot be verified or fallback is explicitly requested.
4. Configure Minos MCP in the selected runtime for live/current subnet data.
5. Install the Minos local skill/persona bundle.
6. Choose a provider path from the Minos setup flow. Minos launches the
   runtime/provider setup command, but provider credentials stay inside
   OpenClaw, Hermes, or the provider OAuth page.

For 1.0.0, Minos does not install or tune local open-source models. Most miners
should use a provider they already trust, such as Claude/Anthropic,
Codex/OpenAI, OpenRouter, or Hermes/Nous Portal.

## OpenClaw

The Minos setup script:

- installs OpenClaw when missing
- installs the `minos-miner` skill into the OpenClaw workspace
- appends Minos context into `AGENTS.md`, `SOUL.md`, and `TOOLS.md` with backups
- installs the OpenClaw Ditto skill
- configures OpenClaw MCP server `minos` at `https://mcp.theminos.ai`
- writes `DITTO_API_KEY` into `~/.openclaw/.env` without printing the key
- configures the OpenClaw gateway for local loopback access
- starts the OpenClaw gateway under PM2 as `openclaw-gateway` on headless/container VMs
- skips full OpenClaw onboarding unless `--run-onboarding` is passed
- checks whether OpenClaw already has a usable provider
- if no usable provider is found, asks the miner to choose OpenAI/Codex,
  Claude/Anthropic, OpenRouter, OpenClaw guided setup, or skip

Provider credentials remain in OpenClaw or the provider OAuth flow. The Minos
script can launch these setup paths:

```bash
openclaw models auth login --provider openai --set-default
openclaw models auth login --provider anthropic --set-default
openclaw models auth login --provider openrouter --set-default
openclaw models auth add
```

Common runtime checks:

```bash
bash scripts/openclaw-tui.sh
openclaw models status
openclaw mcp probe minos --json
openclaw gateway status
pm2 logs openclaw-gateway --lines 80
```

If a miner already knows the provider command they want, they can run it
directly from OpenClaw's normal docs or CLI.

If OpenClaw says Ditto is unavailable because `heyditto` is missing or
`DITTO_API_KEY` is not configured:

```bash
bash scripts/setup_ai_assistant.sh --with-ditto --openclaw
```

## Hermes

The Minos setup script:

- installs Hermes noninteractively when missing
- installs the `minos-miner` skill into `~/.hermes/skills/minos-miner`
- installs or appends Minos context into `~/.hermes/SOUL.md` with backups
- installs the Hermes Ditto skill
- merges Hermes MCP server `minos` into `~/.hermes/config.yaml`
- writes `DITTO_API_KEY` into `~/.hermes/.env` without printing the key
- writes `HERMES_TUI_BACKGROUND=#0A0A0A` for stable SSH terminal rendering
- asks the miner to choose Hermes Portal, full Hermes setup, or skip
- uses Hermes Portal automatically when `--run-hermes-setup` is passed

Provider credentials remain in Hermes or the provider OAuth flow. Common next
steps:

```bash
hermes setup --portal
hermes setup
hermes mcp test minos
hermes --tui --skills minos-miner
hermes chat --cli --skills minos-miner
```

Inside Hermes after MCP config changes:

```text
/reload-mcp
```

If Hermes says Ditto is unavailable because `heyditto` is missing or
`DITTO_API_KEY` is not configured:

```bash
bash scripts/setup_ai_assistant.sh --with-ditto --hermes
```

If `hermes chat` opens an unexpected editor screen in an SSH terminal, confirm
the TUI background variable is present:

```bash
export HERMES_TUI_BACKGROUND="${HERMES_TUI_BACKGROUND:-#0A0A0A}"
hermes chat --cli --skills minos-miner
```

## Secret Handling

Never paste provider API keys, Ditto API keys, wallet secrets, seed phrases,
`.env`, SSH keys, or request signatures into public support channels.

Enter provider keys only into OpenClaw, Hermes, or the provider's own trusted
setup flow.
