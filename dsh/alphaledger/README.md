# dsh-alphaledger

The DeepSeek Harness plugin wrapper for [alphaledger](../README.md).

It contains no code. It exists so that dsh users get one command instead of a YAML
edit:

```console
$ dsh plugin --profile web add dsh-alphaledger
```

<sub>The server itself is on PyPI as `alphaledger-mcp`; this bundle is not on npm yet,
so install it from the checkout until it is: `dsh plugin --profile web add ./dsh/alphaledger`.
Verified on dsh 0.2.0-rc.2 with an isolated `DSH_HOME` — the relative spec is anchored
to an absolute path, pnpm records it as `link:`, and the bundle is registered and loaded
exactly as a registry install would be.</sub>

That inserts one row into the profile's patch:

```yaml
- insert:
    - id: alphaledger
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: alphaledger
        transport: stdio
        command: uvx
        args: ['alphaledger-mcp']
        failOnStartupError: true
        toolCallTimeoutMs: 120000
```

The tools then appear as `mcp__alphaledger__fingerprint`, `mcp__alphaledger__evaluate`,
`mcp__alphaledger__gate`, and `mcp__alphaledger__ledger_stats`.

## The one requirement

**dsh does not install Python.** It starts `uvx`, and `uvx` creates the environment and
fetches `alphaledger-mcp` from PyPI. So the user needs `uv` once:

```console
$ curl -LsSf https://astral.sh/uv/install.sh | sh   # or: winget install astral-sh.uv
```

If `uv` is missing, the plugin refuses to activate (`failOnStartupError: true`) rather
than starting with no tools and leaving the model to silently ignore you.

## Why a separate npm package

An MCP server is an external process; a dsh plugin is the configuration that launches
it. Keeping them apart means the same server is usable from Claude Code, Codex or any
other MCP client, and this bundle stays at four files with no build step and no
JavaScript. Two distribution channels, one implementation.

## Files

```
package.json        dsh.bundle.patch -> cordis.patch.yml, plus exports for icon/locale
cordis.patch.yml    the single insert row shown above
locale/{en,zh}.json title and description for the plugin page
icon.svg            tally marks, because counting is the product
```

`python -m pytest tests/test_dsh_bundle.py` validates the manifest, the patch shape,
the config keys against the client schema, and that every promised file exists. It
cannot prove the host accepts it — only `dsh plugin add` can — so treat it as a typo
guard, not a substitute for a real install.

## Publishing

Two fields are deliberately absent from the manifest. `repository` because the
GitHub repo does not exist yet, and a placeholder URL is worse than none; add it
once it does. `engines.dsh` because the version that introduced bundle support has
not been verified here, and a guessed lower bound can block installs that would
work — set it from the changelog before publishing.

```console
$ cd dsh/alphaledger
$ npm publish --access public
```

Until that runs, install from a path instead:

```console
$ dsh plugin --profile web add ./dsh/alphaledger
```

Two notes from actually running that against dsh 0.2.0-rc.2. First, dsh resolves the
relative spec against the invoking directory, so the recorded dependency is an absolute
`link:` — the checkout has to stay where it is for as long as the plugin is installed.
Second, the install did no network work at all: the profile manifest lists bundle names
under `dsh.profile.bundles`, not as dependencies, so `pnpm add` had nothing to fetch
and finished in under a second.
