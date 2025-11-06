import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import click  # https://click.palletsprojects.com/en/stable/


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


def get_editor() -> str:
    """Gets the user's editor's command for opening a file or folder"""
    editor: str = os.environ.get("EDITOR", "code")
    if not shutil.which(editor):
        click.echo(
            f"Error: editor command `{editor}` not found. Set the EDITOR environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    return editor


def get_waiting_editor(proj_folder: Path) -> str:
    """Gets the user's editor's command for opening a file and waiting for it to close"""
    waiting_editor: str = "code -w"

    try:
        result: subprocess.CompletedProcess = subprocess.run(
            ["git", "-C", str(proj_folder), "config", "get", "core.editor"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert isinstance(result.stdout, str)
        waiting_editor = result.stdout.strip()
    except subprocess.CalledProcessError:
        # try the mode that was deprecated in Git v2.46
        try:
            result: subprocess.CompletedProcess = subprocess.run(
                ["git", "-C", str(proj_folder), "config", "core.editor"],
                check=True,
                capture_output=True,
                text=True,
            )
            assert isinstance(result.stdout, str)
            waiting_editor = result.stdout.strip()
        except subprocess.CalledProcessError:
            pass

    if not shutil.which(waiting_editor.split()[0]):
        click.echo(
            f"Error: editor command `{waiting_editor}` not found. Set your editor in your"
            " .gitconfig (https://git-scm.com/docs/git-config).",
            file=sys.stderr,
        )
        sys.exit(1)

    return waiting_editor


def assert_clean_git(proj_folder: Path) -> None:
    click.echo("Making sure there are no uncommitted changes")
    # https://stackoverflow.com/questions/2657935/checking-for-a-dirty-index-or-untracked-files-with-git
    result: subprocess.CompletedProcess = subprocess.run(
        ["git", "-C", str(proj_folder), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)
    is_git_clean: bool = not result.stdout.strip() and not result.stderr.strip()
    if not is_git_clean:
        click.echo("Error: there are uncommitted changes that should be handled first")
        sys.exit(1)


def generate_random_string(length: int) -> str:
    chars: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    result: list[str] = []
    for _ in range(length):
        result.append(secrets.choice(chars))

    return "".join(result)
