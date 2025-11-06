import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from tempfile import NamedTemporaryFile
from textwrap import dedent
from time import sleep
from typing import Any

import click  # https://click.palletsprojects.com/en/stable/
import paramiko  # https://docs.paramiko.org/en/stable/

from src.config import Config
from src.utils import assert_clean_git
from src.utils import assert_user_has_cmds
from src.utils import get_waiting_editor


repo_folder_path: Path = Path(__file__).parent
pyproject_path: Path = repo_folder_path / "pyproject.toml"

with open(pyproject_path, "rb") as file:
    toml_data: dict[str, Any] = tomllib.load(file)
    toml_project: dict[str, Any] = toml_data["project"]

    app_name: str = toml_project["name"]
    app_version: str = toml_project["version"]
    app_description: str = toml_project["description"]


@click.command()
@click.version_option(app_version, prog_name=app_name)
@click.option("--dry-run", is_flag=True)
def main(dry_run: bool):
    """Deploy the current folder's project."""
    if dry_run:
        click.echo("Dry run")

    assert_user_has_cmds(
        [
            ("git", "https://git-scm.com/"),
            ("rsync", "https://en.wikipedia.org/wiki/Rsync"),
        ]
    )

    config = Config()
    config.load()

    local_proj_folder: Path = Path.cwd()
    if "'" in local_proj_folder.name:
        click.echo(
            "Error: the project folder's name must not contain single quotes", file=sys.stderr
        )
        sys.exit(1)
    elif local_proj_folder == Path("/"):
        click.echo(
            "Error: you cannot choose the root folder as the project folder", file=sys.stderr
        )
        sys.exit(1)

    git_path: Path = local_proj_folder / ".git"
    if not git_path.exists() or not git_path.is_dir():
        click.echo("Error: this folder is not a Git repository", file=sys.stderr)
        sys.exit(1)

    assert_clean_git(local_proj_folder)

    hash_result: subprocess.CompletedProcess = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True
    )
    assert isinstance(hash_result.stdout, str)
    short_commit_hash: str = hash_result.stdout.strip()
    click.echo(f"Preparing to deploy commit {short_commit_hash}")

    waiting_editor: str = get_waiting_editor(local_proj_folder)

    compose_files: list[Path] = []
    compose_name_p: re.Pattern = re.compile(
        r"^(?:docker-)?compose(?:\.[^']+)?\.ya?ml$", flags=re.IGNORECASE
    )
    for entry in local_proj_folder.iterdir():
        if compose_name_p.match(entry.name):
            compose_files.append(entry)
    if not compose_files:
        click.echo("Error: Docker compose file not found", file=sys.stderr)
        sys.exit(1)

    config.ssh_host = click.prompt("SSH host", type=str, default=config.ssh_host)
    config.save()

    click.echo("Reading SSH configuration")
    assert config.ssh_host is not None
    ssh_config = paramiko.SSHConfig.from_path(Path.home() / ".ssh" / "config")
    if config.ssh_host not in ssh_config.get_hostnames():
        click.echo(
            f'Error: SSH host "{config.ssh_host}" was not found in ~/.ssh/config',
            file=sys.stderr,
        )
        sys.exit(1)

    ssh_host = ssh_config.lookup(config.ssh_host)
    if (
        "hostname" not in ssh_host
        or "port" not in ssh_host
        or "user" not in ssh_host
        or "identityfile" not in ssh_host
    ):
        click.echo(
            'Error: the SSH host in ~/.ssh/config must have definitions for "HostName", "Port",'
            ' "User", and "IdentityFile"',
            file=sys.stderr,
        )
        sys.exit(1)

    compose_file_names: list[str] = [file.name for file in compose_files]
    if len(compose_file_names) > 1:
        for name in compose_file_names:
            if name.lower() in [
                "compose.yaml",
                "compose.yml",
                "docker-compose.yaml",
                "docker-compose.yml",
            ]:
                compose_file_names.remove(name)
                compose_file_names.insert(0, name)
                break

        click.echo("Waiting for you to choose the merge order of the compose files")
        prompt: str = (
            "# Choose the merge order of the compose files. Any files you remove"
            " will be skipped.\n"
        )
        c_names_input: str | None = click.edit(
            prompt + "\n".join(compose_file_names),
            editor=waiting_editor,
            extension=".yaml",
            require_save=False,
        )
        if c_names_input is not None:
            if not c_names_input:
                click.echo("Deployment canceled")
                sys.exit(0)
            c_names_input = c_names_input.replace(prompt.strip(), "").strip()

            c_name_order: list[str] = []
            for name in c_names_input.splitlines():
                name = name.strip()
                if not name.startswith("#"):
                    name: str = name
                    if name not in compose_file_names:
                        click.echo(
                            f'Error: "{name}" is not a Docker compose file', file=sys.stderr
                        )
                        sys.exit(1)
                    c_name_order.append(name)
            if not c_name_order:
                click.echo("Deployment canceled")
                sys.exit(0)
            compose_file_names = c_name_order
        click.echo("Compose files merge order: " + ", ".join(compose_file_names))
    if not compose_file_names:
        click.echo("Error: no compose file names found", file=sys.stderr)
        sys.exit(1)
    compose_cmd: str = "docker compose -f '" + "' -f '".join(compose_file_names) + "'"

    click.echo(f"SSHing into {config.ssh_host}")
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    try:
        ssh.connect(
            ssh_host["hostname"],
            port=int(ssh_host["port"]),
            username=ssh_host["user"],
            key_filename=ssh_host["identityfile"],
            timeout=10,  # seconds
        )
    except paramiko.AuthenticationException as err:
        click.echo(f"Error: {err} Did you add the host's SSH key to ssh-agent?", file=sys.stderr)
        sys.exit(1)
    except Exception as err:
        click.echo(f"Error: {repr(err)}", file=sys.stderr)
        sys.exit(1)

    try:  # closes ssh
        click.echo(f"Checking whether the demo port (8228) is already in use on {config.ssh_host}")
        _, stdout, stderr = ssh.exec_command("docker ps --format json", timeout=10)
        if stdout.channel.recv_exit_status() != 0:
            click.echo(f"Error from `docker ps`: {stderr.read().decode()}", file=sys.stderr)
            sys.exit(1)

        container: dict[str, Any] | None = None
        for name in stdout.read().decode().splitlines():
            __container: dict[str, Any] = json.loads(name)
            if "Ports" in __container and isinstance(__container["Ports"], str):
                ports: str = __container["Ports"].split(",")[0]
                assert ports.count(":") == 1, ports.count(":")
                exposed_port: str = ports.split(":")[1].split("-")[0]
                if exposed_port == "8228":
                    container = __container
                    break

        if not container:
            click.echo("The demo port (8228) is available")
        else:
            click.echo(
                f"The demo port (8228) is already in use by {container['Names']}"
                f" ({container['ID']}) on {config.ssh_host}"
            )
            choice: int = click.prompt(
                "What do you want to do?\n1. Shut down the existing services\n2. Cancel deployment\n",
                prompt_suffix="> ",
                type=click.Choice(choices=[1, 2]),
            )
            if choice == 2:  # cancel deployment
                click.echo("Deployment canceled")
                sys.exit(0)
            elif choice == 1:  # shut down the existing services
                click.echo(f"Getting the services' location on {config.ssh_host}")
                _, stdout, stderr = ssh.exec_command(
                    f"docker inspect {container['ID']}", timeout=10
                )
                if stdout.channel.recv_exit_status() != 0:
                    click.echo(
                        f"Error from `docker inspect`: {stderr.read().decode()}", file=sys.stderr
                    )
                    sys.exit(1)
                inspection: dict[str, Any] = json.loads(stdout.read().decode())[0]
                dir: str = inspection["Config"]["Labels"]["com.docker.compose.project.working_dir"]

                click.echo(
                    f"Shutting down {container['Names']} ({container['ID']}) on {config.ssh_host}"
                )
                if not dry_run:
                    _, stdout, stderr = ssh.exec_command(
                        f"cd '{dir}' && {compose_cmd} down", timeout=60
                    )
                    if stdout.channel.recv_exit_status() != 0:
                        click.echo(
                            f"Error from `cd '{dir}' && docker compose down`:"
                            f" {stderr.read().decode()}",
                            file=sys.stderr,
                        )
                        sys.exit(1)
            else:
                raise ValueError("expected input to be 1 or 2")

        config.remote_parent_folder = click.prompt(
            "Remote parent folder", type=Path, default=config.remote_parent_folder
        ).resolve()
        if "'" in str(config.remote_parent_folder):
            click.echo(
                "Error: the remote parent folder must not contain single quotes", file=sys.stderr
            )
            sys.exit(1)
        elif config.remote_parent_folder == Path("/"):
            click.echo(
                "Error: you cannot choose the root folder as the remote project folder",
                file=sys.stderr,
            )
            sys.exit(1)
        config.save()

        click.echo(f"Making sure the project's parent folder exists on {config.ssh_host}")
        if not dry_run:
            _, stdout, stderr = ssh.exec_command(
                f"mkdir --parents '{config.remote_parent_folder}'", timeout=5
            )
            if stdout.channel.recv_exit_status() != 0:
                click.echo(f"Error from `mkdir`: {stderr.read().decode()}", file=sys.stderr)
                sys.exit(1)

        click.echo(
            f"Checking the status of the {local_proj_folder.name} project on {config.ssh_host}"
        )
        remote_proj_folder: Path = config.remote_parent_folder / local_proj_folder.name
        _, stdout, stderr = ssh.exec_command(
            f"""
            if [ -d '{remote_proj_folder}' ]; then
                echo 'project folder exists'
                if [ -d '{remote_proj_folder / ".git"}' ]; then
                    echo '.git folder exists'
                    is_clean=$(git -C '{remote_proj_folder}' status --porcelain)
                    if [ -z "$is_clean" ]; then
                        echo 'Git is clean'
                    fi
                fi
                if [ -f '{remote_proj_folder / ".env"}' ]; then
                    echo '.env file exists'
                fi
            fi
            """,
            timeout=10,
        )
        if stdout.channel.recv_exit_status() != 0:
            click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
            sys.exit(1)
        remote_proj_folder_exists: bool = False
        remote_git_folder_exists: bool = False
        remote_git_is_clean: bool = False
        remote_dotenv_file_exists: bool = False
        for name in stdout.read().decode().splitlines():
            match name:
                case "project folder exists":
                    remote_proj_folder_exists = True
                case ".git folder exists":
                    remote_git_folder_exists = True
                case "Git is clean":
                    remote_git_is_clean = True
                case ".env file exists":
                    remote_dotenv_file_exists = True

        if not remote_proj_folder_exists:
            click.echo(
                f"The {local_proj_folder.name} project does not yet exist on {config.ssh_host}"
            )
        else:
            if remote_git_folder_exists:
                if remote_git_is_clean:
                    click.echo(
                        f"The {local_proj_folder.name} project already exists on"
                        f" {config.ssh_host} and its Git is clean"
                    )
                else:
                    click.secho(
                        f"Warning: the {local_proj_folder.name} project already exists on"
                        f" {config.ssh_host}, but its Git is dirty",
                        fg="yellow",
                    )
            else:
                click.secho(
                    f'A folder named "{local_proj_folder.name}" already exists on'
                    f" {config.ssh_host}, but it has no .git folder"
                )

            choice: int = click.prompt(
                dedent(
                    """\
                    What do you want to do?
                    1. Update files tracked by Git and redeploy
                    2. Delete any volumes and the folder, create a new folder, and redeploy
                    3. Cancel redeployment
                    """
                ),
                prompt_suffix="> ",
                type=click.Choice(choices=[1, 2, 3]),
            )
            if choice == 3:  # cancel redeployment
                click.echo("Redeployment canceled")
                sys.exit(0)
            elif choice == 2:  # delete any volumes and the folder, and create a new folder
                click.echo("Making sure no services are running in the remote project folder")
                if not dry_run:
                    _, stdout, stderr = ssh.exec_command(
                        f"cd '{remote_proj_folder}' && {compose_cmd} down", timeout=60
                    )
                    # even if there are no services running, `docker compose down` should exit with
                    # status code 0
                    if stdout.channel.recv_exit_status() != 0:
                        click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
                        sys.exit(1)

                click.echo("Deleting any volumes")
                if not dry_run:
                    _, stdout, stderr = ssh.exec_command(
                        f"cd '{remote_proj_folder}'"
                        " && docker volume prune --force"
                        " && docker volume rm --force $(docker volume ls --quiet --filter dangling=true)",
                        timeout=30,
                    )
                    if stdout.channel.recv_exit_status() != 0:
                        click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
                        sys.exit(1)

                click.echo("Deleting the folder")
                remote_dotenv_file_exists = False
                if not dry_run:
                    _, stdout, stderr = ssh.exec_command(
                        f"rm -rf '{remote_proj_folder}'", timeout=15
                    )
                    if stdout.channel.recv_exit_status() != 0:
                        click.echo(stderr.read().decode())
                        # The script should continue even if some files cannot be deleted. It's
                        # common for log files to be deletable only by root.

        click.echo("Getting the list of files & folders ignored by Git")
        git_ignores_result: subprocess.CompletedProcess = subprocess.run(
            ["git", "ls-files", "--exclude-standard", "--others", "--ignored", "--directory"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert isinstance(git_ignores_result.stdout, str)
        git_ignores: str = git_ignores_result.stdout

        click.echo(f"Syncing {local_proj_folder.name} to {config.ssh_host}:{remote_proj_folder}")
        if not dry_run:
            git_ignores_file = NamedTemporaryFile(delete=False)
            try:
                git_ignores_file.write(git_ignores.encode())
                git_ignores_file.close()

                subprocess.run(
                    [
                        "rsync",
                        "--quiet",
                        "--recursive",
                        "--compress",
                        "--rsh=ssh",
                        "--perms",
                        "--times",
                        "--group",
                        f"--exclude-from={git_ignores_file.name}",
                        ".",
                        f"{config.ssh_host}:{remote_proj_folder}",
                    ],
                    check=True,
                    timeout=60,
                )
            finally:
                os.unlink(git_ignores_file.name)

        if not remote_dotenv_file_exists:
            # create a remote dotenv file
            dotenv_s: str = ""
            local_dotenv_path: Path = local_proj_folder / ".env"
            if local_dotenv_path.is_file():
                dotenv_s = local_dotenv_path.read_text(encoding="utf8", errors="ignore").rstrip()

            # if it's a FastAPI project, set FORWARDED_ALLOW_IPS
            pyproject_file: Path = local_proj_folder / "pyproject.toml"
            try:
                pyproject_s: str = pyproject_file.read_text(encoding="utf8", errors="ignore")
            except FileNotFoundError:
                pass
            else:
                if "fastapi" in pyproject_s:
                    if click.confirm("Will the deployed service use a proxy?", default=True):
                        config.proxy_ip_address = click.prompt(
                            "Proxy IP address",
                            type=str,
                            default=config.proxy_ip_address or None,
                        )
                        config.save()
                        if config.proxy_ip_address:
                            dotenv_s += f'\n\nFORWARDED_ALLOW_IPS="{config.proxy_ip_address}"  # https://www.uvicorn.org/settings/#http:~:text=Defaults%20to%20the%20%24-,forwarded_allow_ips,-environment%20variable%20if'
                            dotenv_s = dotenv_s.lstrip()
                        else:
                            click.echo("Canceled proxy")

            click.echo("Waiting for you to choose the contents of the remote .env file")
            prompt: str = "# Choose the contents of the remote .env file."
            if dotenv_s.strip():
                prompt += " Here's a copy of the local .env file:"
            prompt += "\n\n"

            new_dotenv_s: str | None = click.edit(
                text=prompt + dotenv_s,
                editor=waiting_editor,
                extension=".env",
                require_save=False,
            )
            if new_dotenv_s is None:
                new_dotenv_s = dotenv_s
            new_dotenv_s = new_dotenv_s.replace(prompt.strip(), "").strip()
            if new_dotenv_s == "":
                click.echo("Skipping creating a .env file in the remote project folder")
            else:
                click.echo("Creating a .env file in the remote project folder")
                heredoc_delim: str = "HEREDOC_DELIM"
                while heredoc_delim in new_dotenv_s:
                    heredoc_delim += "A"
                if not dry_run:
                    _, stdout, stderr = ssh.exec_command(
                        f"cd '{remote_proj_folder}'"
                        " && touch .env"
                        " && chmod 600 .env"
                        f" && cat << {heredoc_delim} > .env\n{new_dotenv_s}\n{heredoc_delim}\n",
                        timeout=10,
                    )
                    if stdout.channel.recv_exit_status() != 0:
                        click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
                        sys.exit(1)

        click.echo("Starting the Docker services")
        if not dry_run:
            _, stdout, stderr = ssh.exec_command(
                f"cd '{remote_proj_folder}' && {compose_cmd} up -d", timeout=500
            )
            if stdout.channel.recv_exit_status() != 0:
                click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
                sys.exit(1)

        click.echo("Monitoring the services' statuses (press Ctrl+C to stop)")
        if not dry_run:
            try:
                while True:
                    sleep(5)
                    _, stdout, stderr = ssh.exec_command(
                        f"cd '{remote_proj_folder}' && {compose_cmd} ps --format json", timeout=10
                    )
                    if stdout.channel.recv_exit_status() != 0:
                        click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
                        sys.exit(1)

                    stdout_s: str = stdout.read().decode()
                    if not stdout_s:
                        click.echo("Error: no services are running", file=sys.stderr)
                        sys.exit(1)

                    click.echo("\t------------------------------")
                    for name in stdout_s.splitlines():
                        service: dict[str, Any] = json.loads(name)
                        click.echo(f"\t{service['Name']}: {service['Status']}")
            except KeyboardInterrupt:
                pass
    finally:
        ssh.close()

    click.echo("\nDeployment attempt complete")
    if dry_run:
        click.echo("Dry run complete")


if __name__ == "__main__":
    main()
