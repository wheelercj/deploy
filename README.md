# deploy

Quickly deploy a web app to a remote server.

This script is best when you want to quickly demo something, such as during a technical interview. You could configure a reverse proxy to forward requests from a demo subdomain like `demo.example.com` to the IP address and port you will deploy a service at, then use this script to deploy it there. Then whoever you are giving the demo to can try your service themselves.

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

Then you can run `deploy --help` (if you name the file `deploy` and it's in PATH).
