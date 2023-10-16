#!/usr/bin/env python
import subprocess
from os import makedirs
from pathlib import Path

import click
from yaml.parser import ParserError

from dbt_copilot_helper.utils.aws import get_codestar_connection_arn
from dbt_copilot_helper.utils.click import ClickDocOptGroup
from dbt_copilot_helper.utils.files import BOOTSTRAP_SCHEMA
from dbt_copilot_helper.utils.files import PIPELINES_SCHEMA
from dbt_copilot_helper.utils.files import load_and_validate_config
from dbt_copilot_helper.utils.files import mkfile
from dbt_copilot_helper.utils.messages import abort_with_error
from dbt_copilot_helper.utils.template import setup_templates
from dbt_copilot_helper.utils.versioning import (
    check_copilot_helper_version_needs_update,
)


@click.group(chain=True, cls=ClickDocOptGroup)
def pipeline():
    """Pipeline commands."""
    check_copilot_helper_version_needs_update()


@pipeline.command()
@click.option("-d", "--directory", type=str, default=".")
def generate(directory="."):
    templates = setup_templates()

    try:
        app_config = load_and_validate_config("bootstrap.yml", BOOTSTRAP_SCHEMA)
    except ParserError:
        abort_with_error("The bootstrap.yml file is invalid")
    app_name = app_config["app"]

    try:
        pipeline_environments = load_and_validate_config("pipelines.yml", PIPELINES_SCHEMA)
    except FileNotFoundError:
        abort_with_error("There is no pipelines.yml")
    except ParserError:
        abort_with_error("The pipelines.yml file is invalid")

    git_repo = get_git_remote()
    if not git_repo:
        abort_with_error("The current directory is not a git repository")

    codestar_connection_arn = get_codestar_connection_arn(app_name)
    if codestar_connection_arn is None:
        abort_with_error("There is no CodeStar Connection to use")

    base_path = Path(directory)
    pipelines_environments_dir = base_path / f"copilot/pipelines/{ app_config['app'] }-environments"
    overrides_dir = pipelines_environments_dir / "overrides"

    makedirs(overrides_dir)

    template_data = {
        "app_name": app_name,
        "git_repo": git_repo,
        "codestar_connection_arn": codestar_connection_arn,
        "pipeline_environments": pipeline_environments["environments"],
    }

    contents = templates.get_template("pipeline/buildspec.yml").render(template_data)
    click.echo(mkfile(base_path, pipelines_environments_dir / "buildspec.yml", contents))

    contents = templates.get_template("pipeline/manifest.yml").render(template_data)
    click.echo(mkfile(base_path, pipelines_environments_dir / "manifest.yml", contents))

    contents = templates.get_template("pipeline/overrides/cfn.patches.yml").render(template_data)
    click.echo(
        mkfile(base_path, pipelines_environments_dir / "overrides/cfn.patches.yml", contents)
    )


def get_git_remote():
    git_repo = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True
    ).stdout.strip()

    if not git_repo:
        return

    domain, repo = git_repo.split("@")[1].split(":")

    return f"https://{domain}/{repo}"
