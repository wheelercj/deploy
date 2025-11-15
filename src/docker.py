import json
import re
import sys
from pathlib import Path
from time import sleep
from typing import Any

import click  # https://click.palletsprojects.com/en/stable/
import paramiko  # https://docs.paramiko.org/en/stable/


def get_compose_files(local_proj_folder: Path) -> list[Path]:
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

    return compose_files


def get_compose_cmd(compose_files: list[Path], waiting_editor: str, verbose: bool) -> str:
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
            for line in c_names_input.splitlines():
                line = line.strip()
                if not line.startswith("#"):
                    name: str = line
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
        if verbose:
            click.echo("Compose files merge order: " + ", ".join(compose_file_names))
    if not compose_file_names:
        click.echo("Error: no compose file names found", file=sys.stderr)
        sys.exit(1)

    return "docker compose -f '" + "' -f '".join(compose_file_names) + "'"


def start(
    dry_run: bool, remote_proj_folder: Path, compose_cmd: str, ssh: paramiko.SSHClient
) -> None:
    click.echo("Starting the Docker services")
    if not dry_run:
        _, stdout, stderr = ssh.exec_command(
            f"cd '{remote_proj_folder}' && {compose_cmd} up -d", timeout=500
        )
        if stdout.channel.recv_exit_status() != 0:
            click.echo(f"Error: {stderr.read().decode()}", file=sys.stderr)
            sys.exit(1)


def monitor(
    dry_run: bool, remote_proj_folder: Path, compose_cmd: str, ssh: paramiko.SSHClient
) -> None:
    if sys.platform == "darwin":
        click.echo("Monitoring the services' statuses (press Cmd+C to stop)")
    else:
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
