# huvcli

Small CLI coding agent for friends.

## Install

Windows:

```powershell
.\scripts\install.ps1 -ApiKey "your-key"
```

macOS/Linux:

```sh
HUV_API_KEY="your-key" ./scripts/install.sh
```

Developer editable install:

```powershell
.\scripts\install.ps1 -Editable
```

Update later:

```powershell
.\scripts\update.ps1
```

## Use

```powershell
huv "explain this repo"
huv chat
huv models
huv assets
```

Huv reads [HUV.md](HUV.md) from the current project when present and adds it to
the agent instructions.

By default, file writes and shell commands ask before running.

```powershell
huv --yes "add tests for this package"
```

The agent prefers small unified-diff patches for edits. Commands that look
destructive are blocked unless the model explicitly marks them as intentional.

## Config

Optional environment variables:

```powershell
$env:HUV_API_KEY="..."
$env:HUV_MODEL="MiniMax-M2.7"
```

No client-side rate limiter is included. Any remote-side limits still apply.

## Bundled Agent Assets

This repo includes portable copies of selected skills and plugin skill packs under
the installed `huvcli.agent_assets` package:

- coding/browser/design/security/SEO skills
- document, spreadsheet, presentation, and browser plugin skill packs

Use `huv assets` to list them on another PC after install.
