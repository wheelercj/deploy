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


@click.command(epilog="For more details, see https://github.com/wheelercj/deploy")
@click.version_option(app_version, prog_name=app_name)
@click.option("--dry-run", is_flag=True, help="Preview this script without making changes.")
@click.option("--verbose", is_flag=True, help="Include more details in the output.")
@click.option("--config-path", is_flag=True, help="Show the config file's path and exit.")
def main(dry_run: bool, verbose: bool, config_path: bool):
    """Deploy the current folder's project."""
    if config_path:
        click.echo(Path(click.get_app_dir("deploy")) / "config.json")
        sys.exit(0)

    if dry_run:
        click.echo("Dry run")

    assert_user_has_cmds(
        {
            "git": "https://git-scm.com/",
            "rsync": "https://en.wikipedia.org/wiki/Rsync",
        }
    )

    config = Config()
    config.load()

    local_proj_folder: Path = get_local_proj_folder()

    git_folder: Path = local_proj_folder / ".git"
    if not git_folder.exists() or not git_folder.is_dir():
        click.echo("Error: this folder is not a Git repository", file=sys.stderr)
        sys.exit(1)

    git.assert_clean(local_proj_folder, verbose)

    hash: str = git.get_latest_commit_short_hash()
    click.echo(f"Preparing to deploy commit {hash}")

    waiting_editor_cmd: str = git.get_waiting_editor_cmd(local_proj_folder)

    compose_files: list[Path] = docker.get_compose_files(local_proj_folder)

    config.ssh_host = click.prompt("SSH host", type=str, default=config.ssh_host)
    assert config.ssh_host is not None
    ssh_host_d: paramiko.SSHConfigDict = sshlib.get_host(config.ssh_host, verbose)
    config.save()

    compose_cmd: str = docker.get_compose_cmd(compose_files, waiting_editor_cmd, verbose)

    with sshlib.connect(config.ssh_host, ssh_host_d, verbose) as ssh:
        remote.get_parent_folder(dry_run, ssh, config, verbose)
        assert config.remote_parent_folder is not None
        remote_proj_folder: Path = config.remote_parent_folder / local_proj_folder.name
        remote_status: remote.ProjStatus = remote.get_proj_status(
            remote_proj_folder, ssh, config, verbose
        )

        if remote_status.folder_exists:
            remote.handle_existing_proj(
                dry_run, remote_proj_folder, remote_status, compose_cmd, ssh, config, verbose
            )
        else:
            click.echo(
                f"The {local_proj_folder.name} project does not exist on {config.ssh_host} yet"
            )

        remote.sync_proj(dry_run, remote_proj_folder, config, verbose)

        if remote_status.dotenv_file_exists:
            click.echo(f"{config.ssh_host} already has a .env file for {local_proj_folder.name}")
        else:
            remote.create_dotenv(
                dry_run,
                local_proj_folder,
                remote_proj_folder,
                waiting_editor_cmd,
                ssh,
                config,
                verbose,
            )

        docker.start(dry_run, remote_proj_folder, compose_cmd, ssh)
        docker.monitor(dry_run, remote_proj_folder, compose_cmd, ssh)

    click.echo("\nDeployment attempt complete")
    if dry_run:
        click.echo("Dry run complete")
    click.echo(
        "Remember to run any commands that must be run after deploying, such as database migration"
        " commands"
    )


def assert_user_has_cmds(cmds: dict[str, str]) -> None:
    """Exits with an error if the user does not have all of the given commands

    Parameters
    ----------
    cmds: dict[str, str]
        The commands that must exist. The keys are command names and the values are URLs for info
        about the commands.
    """
    missing_cmds: list[str] = []
    for name, url in cmds.items():
        name = name.split()[0]
        if not shutil.which(name):
            missing_cmds.append(name + " " + url)
    if missing_cmds:
        click.echo(
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
    main(prog_name=app_name)
