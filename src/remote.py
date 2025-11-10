import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from textwrap import dedent

import click  # https://click.palletsprojects.com/en/stable/
import paramiko  # https://docs.paramiko.org/en/stable/

from src import git
from src.config import Config


@dataclass
class ProjStatus:
    folder_exists: bool = False
    git_folder_exists: bool = False
    git_is_clean: bool = False
    dotenv_file_exists: bool = False


def get_parent_folder(
    dry_run: bool, ssh: paramiko.SSHClient, config: Config, verbose: bool
) -> None:
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

    if verbose:
        click.echo(f"Making sure the project's parent folder exists on {config.ssh_host}")
    if not dry_run:
        _, stdout, stderr = ssh.exec_command(
            f"mkdir --parents '{config.remote_parent_folder}'", timeout=5
        )
        if stdout.channel.recv_exit_status() != 0:
            click.echo(f"Error from `mkdir`: {stderr.read().decode()}", file=sys.stderr)
            sys.exit(1)


def get_proj_status(
    remote_proj_folder: Path, ssh: paramiko.SSHClient, config: Config, verbose: bool
) -> ProjStatus:
    if verbose:
        click.echo(
            f"Checking the status of the {remote_proj_folder.name} project on {config.ssh_host}"
        )
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

    remote_status = ProjStatus()
    for name in stdout.read().decode().splitlines():
        match name:
            case "project folder exists":
                remote_status.folder_exists = True
            case ".git folder exists":
                remote_status.git_folder_exists = True
            case "Git is clean":
                remote_status.git_is_clean = True
            case ".env file exists":
                remote_status.dotenv_file_exists = True

    return remote_status


def handle_existing_proj(
    dry_run: bool,
    remote_proj_folder: Path,
    remote_status: ProjStatus,
    compose_cmd: str,
    ssh: paramiko.SSHClient,
    config: Config,
    verbose: bool,
) -> None:
    if remote_status.git_folder_exists:
        if remote_status.git_is_clean:
            click.echo(
                f"The {remote_proj_folder.name} project already exists on"
                f" {config.ssh_host} and its Git is clean"
            )
        else:
            click.secho(
                f"Warning: the {remote_proj_folder.name} project already exists on"
                f" {config.ssh_host}, but its Git is dirty",
                fg="yellow",
            )
    else:
        click.secho(
            f'A folder named "{remote_proj_folder.name}" already exists on'
            f" {config.ssh_host}, but it has no .git folder",
            fg="yellow",
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
        show_choices=False,
    )
    if choice == 3:  # cancel redeployment
        click.echo("Redeployment canceled")
        sys.exit(0)
    elif choice == 2:  # delete any volumes and the folder, and create a new folder
        __delete_project(dry_run, remote_proj_folder, remote_status, compose_cmd, ssh, verbose)


def sync_proj(dry_run: bool, remote_proj_folder: Path, config: Config, verbose: bool) -> None:
    click.echo(f"Syncing {remote_proj_folder.name} to {config.ssh_host}:{remote_proj_folder}")
    git_ignores: str = git.get_ignores(verbose)
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


def create_dotenv(
    dry_run: bool,
    local_proj_folder: Path,
    remote_proj_folder: Path,
    waiting_editor_cmd: str,
    ssh: paramiko.SSHClient,
    config: Config,
    verbose: bool,
) -> None:
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
        editor=waiting_editor_cmd,
        extension=".env",
        require_save=False,
    )
    if new_dotenv_s is None:
        new_dotenv_s = dotenv_s
    new_dotenv_s = new_dotenv_s.replace(prompt.strip(), "").strip()
    if new_dotenv_s == "":
        click.echo("Skipping creating a .env file in the remote project folder")
    else:
        if verbose:
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


def __delete_project(
    dry_run: bool,
    remote_proj_folder: Path,
    remote_status: ProjStatus,
    compose_cmd: str,
    ssh: paramiko.SSHClient,
    verbose: bool,
):
    if verbose:
        click.echo("Making sure no services are running in the remote project folder")
    if not dry_run:
        _, stdout, stderr = ssh.exec_command(
            f"cd '{remote_proj_folder}' && {compose_cmd} down", timeout=60
        )
        # even if there are no services running, `docker compose down` should exit with status
        # code 0
        if stdout.channel.recv_exit_status() != 0:
            click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
            sys.exit(1)

    if verbose:
        click.echo("Checking for volumes")
    _, stdout, stderr = ssh.exec_command(
        f"cd '{remote_proj_folder}' && {compose_cmd} volumes --format json", timeout=10
    )
    if stdout.channel.recv_exit_status() != 0:
        click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
        sys.exit(1)
    volume_names: list[str] = []
    for line in stdout.read().decode().splitlines():
        volume_names.append(json.loads(line)["Name"])
    click.echo(
        f"Found {len(volume_names)} volumes belonging to the {remote_proj_folder.name} project"
    )
    if volume_names:
        click.echo("Deleting volumes")
        volume_names_s: str = " ".join(volume_names)
        if not dry_run:
            _, stdout, stderr = ssh.exec_command(f"docker volume rm {volume_names_s}", timeout=20)
            if stdout.channel.recv_exit_status() != 0:
                click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
                sys.exit(1)

    click.echo("Deleting the folder")
    remote_status.dotenv_file_exists = False
    if not dry_run:
        _, stdout, stderr = ssh.exec_command(f"rm -rf '{remote_proj_folder}'", timeout=15)
        if stdout.channel.recv_exit_status() != 0:
            click.echo(stderr.read().decode())
            # The script should continue even if some files cannot be deleted. It's common for
            # log files to be deletable only by root.
