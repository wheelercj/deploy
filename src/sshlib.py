import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import click  # https://click.palletsprojects.com/en/stable/
import paramiko  # https://docs.paramiko.org/en/stable/


def get_host(ssh_host_s: str, verbose: bool) -> paramiko.SSHConfigDict:
    if verbose:
        click.echo("Reading SSH configuration")
    ssh_config: paramiko.SSHConfig = paramiko.SSHConfig.from_path(Path.home() / ".ssh" / "config")
    if ssh_host_s not in ssh_config.get_hostnames():
        click.echo(
            f'Error: SSH host "{ssh_host_s}" was not found in ~/.ssh/config',
            file=sys.stderr,
        )
        sys.exit(1)

    ssh_host: paramiko.SSHConfigDict = ssh_config.lookup(ssh_host_s)
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

    return ssh_host


@contextmanager
def connect(
    ssh_host: str, ssh_host_d: paramiko.SSHConfigDict, verbose: bool
) -> Generator[paramiko.SSHClient]:
    if verbose:
        click.echo(f"SSHing into {ssh_host}")

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))

    identity_file_path: str = ""
    if isinstance(ssh_host_d["identityfile"], list):
        identity_file_path = ssh_host_d["identityfile"][0]
    else:
        identity_file_path = ssh_host_d["identityfile"]

    while True:
        try:
            ssh.connect(
                ssh_host_d["hostname"],
                port=int(ssh_host_d["port"]),
                username=ssh_host_d["user"],
                key_filename=identity_file_path,
                timeout=10,  # seconds
            )
            break
        except paramiko.AuthenticationException as err:
            err_s: str = str(err).rstrip(".") + "."
            click.echo(
                f"Error: {err_s} Did you add the host's SSH key to ssh-agent?", file=sys.stderr
            )
            sys.exit(1)
        except paramiko.SSHException as err:
            if "not found in known_hosts" not in str(err):
                raise
            click.echo(err)
            if click.confirm("Add the server to known_hosts?"):
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            else:
                click.echo("Deployment canceled")
                sys.exit(0)
        except Exception as err:
            click.echo(f"Error: {repr(err)}", file=sys.stderr)
            sys.exit(1)

    check: str = click.style("🗸", fg="green")
    click.echo(f"{check} Connected to {ssh_host}")

    try:
        yield ssh
    finally:
        ssh.close()
