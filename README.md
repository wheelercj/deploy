# deploy

Simplifies deployment of your application to your on-prem infrastructure.

```
$ cd url-shortener
$ deploy
Making sure there are no uncommitted changes
Preparing to deploy commit 2fe854e
SSH host: app-server
🗸 Connected to app-server
Remote parent folder [/home/chris/repos]:
The url-shortener project does not exist on app-server yet
Syncing url-shortener to app-server:/home/chris/repos/url-shortener
Waiting for you to choose the contents of the remote .env file
Starting the Docker services
Monitoring the services' statuses (press Ctrl+C to stop monitoring)
	------------------------------
	postgres: Up 7 seconds
	url_shortener: Up 6 seconds
	------------------------------
	postgres: Up 12 seconds
	url_shortener: Up 12 seconds
	------------------------------
	postgres: Up 18 seconds
	url_shortener: Up 17 seconds
^C
Deployment attempt complete
```

The script looks for at least one Docker compose file, an SSH configuration at `~/.ssh/config`, and an SSH key in ssh-agent. The only files sent to your remote server are a new .env file and the files tracked by Git. If the project's files are already on the remote server, you are given the options to sync the files tracked by Git, or delete and recreate the remote project (including creating a new .env file and new volumes), or cancel the deployment. Files are synced to the remote server using rsync.

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
