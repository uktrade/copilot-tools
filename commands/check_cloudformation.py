#!/usr/bin/env python
import os
from pathlib import Path
from subprocess import run

import click

from commands.bootstrap_cli import make_config
from commands.copilot_cli import make_storage

BASE_DIR = Path(__file__).parent.parent


@click.group(invoke_without_command=True, chain=True)
@click.pass_context
def check_cloudformation(ctx):
    """Runs the checks passed in the command arguments. If no argument is passed, it will run all the checks."""

    ctx.obj = {"passing_checks": [], "failing_checks": []}

    click.secho(f"\n>>> Preparing CloudFormation templates\n", fg="yellow")
    os.chdir(f"{BASE_DIR}/tests/test-application")
    ctx.invoke(make_config, config_file="bootstrap.yml")
    ctx.invoke(make_storage, storage_config_file="storage.yml")

    if ctx.invoked_subcommand is None:
        click.secho(f"\n>>> Running all checks", fg="yellow")
        for name, command in ctx.command.commands.items():
            ctx.invoke(command)


@check_cloudformation.command()
@click.pass_context
def lint(ctx):
    """Runs cfn-lint against the generated CloudFormation templates."""

    BASE_DIR = Path(__file__).parent.parent

    command = ["cfn-lint", f"{BASE_DIR}/tests/test-application/copilot/**/addons/*.yml"]

    click.secho(f"\n>>> Running lint check", fg="yellow")
    click.secho(f"""    {" ".join(command)}\n""", fg="yellow")

    result = run(command, capture_output=True)

    click.secho(result.stdout.decode())
    if result.returncode == 0:
        ctx.obj["passing_checks"].append("lint")
    else:
        click.secho(result.stderr.decode())
        ctx.obj["failing_checks"].append("lint")


@check_cloudformation.result_callback()
@click.pass_context
def process_result(ctx, result):
    if ctx.obj["passing_checks"]:
        click.secho("\nThe CloudFormation templates passed the following checks :-)", fg="green")
        for passing_check in ctx.obj["passing_checks"]:
            click.secho(f"  - {passing_check}", fg="green")

    if ctx.obj["failing_checks"]:
        click.secho("\nThe CloudFormation templates failed the following checks :-(", fg="red")
        for failing_check in ctx.obj["failing_checks"]:
            click.secho(f"  - {failing_check}", fg="red")
        exit(1)

