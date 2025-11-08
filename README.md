# deploy

Quickly deploy a web app to a remote server.

This script is best when you want to quickly demo something, such as during a technical interview. You could configure a reverse proxy to forward requests from a demo subdomain like `demo.example.com` to the IP address and port you will deploy a service at, then use this script to deploy it there. Then whoever you are giving the demo to can try your service themselves.

```
$ cd url-shortener
$ deploy
Making sure there are no uncommitted changes
Preparing to deploy commit 2fe854e
SSH host: app-server
SSHing into app-server
url-shortener port [8228]:
🗸 Port 8228 is available
Remote parent folder [/home/chris/repos]:
Checking the status of the url-shortener project on app-server
The url-shortener project does not exist on app-server yet
Syncing url-shortener to app-server:/home/chris/repos/url-shortener
Waiting for you to choose the contents of the remote .env file
Creating a .env file in the remote project folder
Starting the Docker services
Monitoring the services' statuses (press Ctrl+C to stop)
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
