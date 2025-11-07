import secrets
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

import click  # https://click.palletsprojects.com/en/stable/
import paramiko  # https://docs.paramiko.org/en/stable/

from src import docker
from src import git
from src import remote
from src import sshlib
from src.config import Config


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

    local_proj_folder: Path = get_local_proj_folder()

    git_folder: Path = local_proj_folder / ".git"
    if not git_folder.exists() or not git_folder.is_dir():
        click.echo("Error: this folder is not a Git repository", file=sys.stderr)
        sys.exit(1)

    git.assert_clean(local_proj_folder)

    hash: str = git.get_latest_commit_short_hash()
    click.echo(f"Preparing to deploy commit {hash}")

    waiting_editor_cmd: str = git.get_waiting_editor_cmd(local_proj_folder)

    compose_files: list[Path] = docker.get_compose_files(local_proj_folder)

    config.ssh_host = click.prompt("SSH host", type=str, default=config.ssh_host)
    config.save()

    assert config.ssh_host is not None
    ssh_host_d: paramiko.SSHConfigDict = sshlib.get_host(config.ssh_host)

    compose_cmd: str = docker.get_compose_cmd(compose_files, waiting_editor_cmd)

    with sshlib.connect(config.ssh_host, ssh_host_d) as ssh:
        config.remote_port = click.prompt("Port", type=int, default=config.remote_port or 8228)
        config.save()
        docker.check_port(dry_run, compose_cmd, ssh, config)

        remote.get_parent_folder(dry_run, ssh, config)
        remote_proj_folder: Path = config.remote_parent_folder / local_proj_folder.name
        remote_status: remote.ProjStatus = remote.get_proj_status(remote_proj_folder, ssh, config)

        if remote_status.folder_exists:
            remote.handle_existing_proj(
                dry_run, remote_proj_folder, remote_status, compose_cmd, ssh, config
            )
        else:
            click.echo(
                f"The {local_proj_folder.name} project does not yet exist on {config.ssh_host}"
            )

        remote.sync_proj(dry_run, remote_proj_folder, config)

        if not remote_status.dotenv_file_exists:
            remote.create_dotenv(
                dry_run, local_proj_folder, remote_proj_folder, waiting_editor_cmd, ssh, config
            )

        docker.start(dry_run, remote_proj_folder, compose_cmd, ssh)
        docker.monitor(dry_run, remote_proj_folder, compose_cmd, ssh)

    click.echo("\nDeployment attempt complete")
    if dry_run:
        click.echo("Dry run complete")


def assert_user_has_cmds(cmds: list[tuple[str, str]]) -> None:
    """Exits with an error if the user does not have all of the given commands

    Parameters
    ----------
    cmds: list[tuple[str, str]]
        The commands that must exist. The first element of each tuple is the command's name, and
        the second is a URL for info about the command.
    """
    missing_cmds: list[str] = []
    for cmd in cmds:
        name, url = cmd[0], cmd[1]
        if not shutil.which(name):
            missing_cmds.append(name + " " + url)
    if missing_cmds:
        print(
            "Error: missing required executable(s):\n\t" + "\n\t".join(missing_cmds),
            file=sys.stderr,
        )
        sys.exit(1)


def get_local_proj_folder() -> Path:
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

    return local_proj_folder


def generate_random_string(length: int) -> str:
    chars: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    result: list[str] = []
    for _ in range(length):
        result.append(secrets.choice(chars))

    return "".join(result)


if __name__ == "__main__":
    main()
