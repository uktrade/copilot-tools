#!/usr/bin/env python

from importlib.metadata import version

import click

from dbt_copilot_helper.commands.application import application as application_commands
from dbt_copilot_helper.commands.bootstrap import bootstrap as bootstrap_commands
from dbt_copilot_helper.commands.check_cloudformation import (
    check_cloudformation as check_cloudformation_command,
)
from dbt_copilot_helper.commands.codebase import codebase as codebase_commands
from dbt_copilot_helper.commands.conduit import conduit as conduit_commands
from dbt_copilot_helper.commands.config import config as config_commands
from dbt_copilot_helper.commands.copilot import copilot as copilot_commands
from dbt_copilot_helper.commands.dns import cdn as cdn_commands
from dbt_copilot_helper.commands.dns import domain as domain_commands
from dbt_copilot_helper.commands.environment import environment as environment_commands
from dbt_copilot_helper.commands.generate import generate as generate_commands
from dbt_copilot_helper.commands.pipeline import pipeline as pipeline_commands
from dbt_copilot_helper.utils.click import ClickDocOptGroup


@click.group(cls=ClickDocOptGroup)
@click.version_option(
    version=version("dbt-copilot-tools"),
    message=f"dbt-copilot-tools %(version)s",
)
def copilot_helper():
    click.secho(
        "DeprecationWarning: The package 'dbt-copilot-tools' has been deprecated. Please switch to using https://pypi.org/project/dbt-platform-helper/.",
        fg="magenta",
    )


copilot_helper.add_command(bootstrap_commands)
copilot_helper.add_command(check_cloudformation_command)
copilot_helper.add_command(codebase_commands)
copilot_helper.add_command(conduit_commands)
copilot_helper.add_command(config_commands)
copilot_helper.add_command(copilot_commands)
copilot_helper.add_command(domain_commands)
copilot_helper.add_command(cdn_commands)
copilot_helper.add_command(environment_commands)
copilot_helper.add_command(generate_commands)
copilot_helper.add_command(pipeline_commands)
copilot_helper.add_command(application_commands)

if __name__ == "__main__":
    copilot_helper()
