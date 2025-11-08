import os
import shutil
import subprocess
import sys
from pathlib import Path

import click  # https://click.palletsprojects.com/en/stable/


def assert_clean(proj_folder: Path, verbose: bool) -> None:
    if verbose:
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
        click.echo(
            "Error: there are uncommitted changes that should be handled first", file=sys.stderr
        )
        sys.exit(1)


def get_latest_commit_short_hash() -> str:
    hash_result: subprocess.CompletedProcess = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True
    )
    assert isinstance(hash_result.stdout, str)
    return hash_result.stdout.strip()


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


def get_waiting_editor_cmd(proj_folder: Path) -> str:
    """Gets the user's editor's command for opening a file and waiting for it to close"""
    waiting_editor_cmd: str = "code -w"

    try:
        result: subprocess.CompletedProcess = subprocess.run(
            ["git", "-C", str(proj_folder), "config", "get", "core.editor"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert isinstance(result.stdout, str)
        waiting_editor_cmd = result.stdout.strip()
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
            waiting_editor_cmd = result.stdout.strip()
        except subprocess.CalledProcessError:
            pass

    if not shutil.which(waiting_editor_cmd.split()[0]):
        click.echo(
            f"Error: editor command `{waiting_editor_cmd}` not found. Set your editor in your"
            " .gitconfig (https://git-scm.com/docs/git-config).",
            file=sys.stderr,
        )
        sys.exit(1)

    return waiting_editor_cmd


def get_ignores(verbose: bool) -> str:
    if verbose:
        click.echo("Getting the list of files & folders ignored by Git")
    git_ignores_result: subprocess.CompletedProcess = subprocess.run(
        ["git", "ls-files", "--exclude-standard", "--others", "--ignored", "--directory"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert isinstance(git_ignores_result.stdout, str)
    return git_ignores_result.stdout
