import glob
from subprocess import run

import click


def get_lint_result(path: str, ignore_path: str = None, ignore_checks: list = []):
    command = ["cfn-lint", path]
    if ignore_path:
        command.extend(["--ignore-templates", ignore_path])
    if ignore_checks:
        for check in ignore_checks:
            command.extend(["--ignore-checks", check])

    click.secho(f"\n>>> Running lint check", fg="yellow")
    click.secho(f"""    {" ".join(command)}\n""", fg="yellow")

    return run(command, capture_output=True)


def get_check_security_result(path: str, ignore_path: str = None):
    matching_files = glob.glob(path)
    command = ["checkov", "--quiet", "--framework", "cloudformation"]

    for file in matching_files:
        command.extend(["--file", file])

    if ignore_path:
        for ignored_file in glob.glob(ignore_path):
            command.extend(["--skip-path", ignore_path])

    click.secho(f"\n>>> Running security check", fg="yellow")
    click.secho(f"""    {" ".join(command)}\n""", fg="yellow")

    return run(command, capture_output=True)
