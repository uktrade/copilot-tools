#!/usr/bin/env python
from pathlib import Path

import click

from dbt_platform_helper.utils.click import ClickDocOptGroup
from dbt_platform_helper.utils.cloudformation import get_check_security_result
from dbt_platform_helper.utils.cloudformation import get_lint_result

BASE_DIR = Path(__file__).parent.parent.parent


@click.group(invoke_without_command=True, chain=True, cls=ClickDocOptGroup)
@click.option("-d", "--directory", type=str, default="copilot")
@click.pass_context
def check_cloudformation(ctx: click.Context, directory: str) -> None:
    """
    Runs the checks passed in the command arguments.

    If no argument is passed, it will run all the checks.
    """
    ctx.ensure_object(dict)

    if ctx.invoked_subcommand is None:
        click.secho(f"\n>>> Running all checks", fg="yellow")
        for command in ctx.command.commands.values():
            ctx.invoke(command)


@check_cloudformation.command()
@click.option("-d", "--directory", type=str, default="copilot")
@click.option("-i", "--ignore-checks", type=str, multiple=True, default=[])
@click.pass_context
def lint(ctx: click.Context, directory: str, ignore_checks: list) -> bool:
    """Runs cfn-lint against the generated CloudFormation templates."""
    addons_manifests = f"{directory}/**/addons/*.yml"
    # addons.parameters.yml is not a CloudFormation template file
    ignore_addons_params = f"{directory}/**/addons/addons.parameters.yml"
    # "W2001 Parameter Env not used" is ignored becomes Copilot addons require
    # parameters even if they are not used in the Cloudformation template.
    ignore_checks_list = list(ignore_checks)
    ignore_checks_list.append("W2001")

    result = get_lint_result(addons_manifests, ignore_addons_params, ignore_checks_list)
    success = result.returncode == 0

    ctx.obj["lint"] = {
        "success": success,
        "message": result.stdout.decode() if not success else None,
    }

    return success


@check_cloudformation.command()
@click.option("-d", "--directory", type=str, default="copilot")
@click.pass_context
def check_security(ctx: click.Context, directory: str) -> bool:
    addons_manifests = f"{directory}/**/addons/*.yml"
    # # addons.parameters.yml is not a CloudFormation template file
    ignore_addons_params = f"{directory}/**/addons/addons.parameters.yml"

    result = get_check_security_result(addons_manifests, ignore_addons_params)
    success = result.returncode == 0

    ctx.obj["check-security"] = {
        "success": success,
        "message": result.stdout.decode() if not success else None,
    }

    return success


@check_cloudformation.result_callback()
@click.pass_context
def process_result(ctx: click.Context, result, directory) -> None:
    successful = {k: v for k, v in ctx.obj.items() if v["success"]}
    failed = {k: v for k, v in ctx.obj.items() if not v["success"]}
    if successful:
        click.secho("\nThe CloudFormation templates passed the following checks:", fg="green")
        for subcommand_name in successful:
            click.secho(f"  - {subcommand_name}", fg="white")
    if failed:
        click.secho("\nThe CloudFormation templates failed the following checks:", fg="red")
        for subcommand_name in failed:
            message = failed[subcommand_name]["message"]
            click.secho(f"  - {subcommand_name} [{message}]", fg="white")
        exit(1)
    exit(0)
