# deploy

Quickly deploy a web app to a remote server.

## Install

1. Install [uv](https://docs.astral.sh/uv/) if you haven't already
2. `git clone git@github.com:wheelercj/deploy.git && cd deploy`
3. `uv run main.py --help`

You might want to create a custom command for this. Here's a sample Bash file:

```bash
#!/usr/bin/env bash
set -euo pipefail

uv run --project "$HOME/repos/deploy" "$HOME/repos/deploy/main.py" "$@"
```

Then you can run `deploy --help`.
