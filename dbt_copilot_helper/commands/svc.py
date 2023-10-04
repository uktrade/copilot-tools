#!/usr/bin/env python

import re
import subprocess

import boto3
import click

from dbt_copilot_helper.utils.click import ClickDocOptGroup
from dbt_copilot_helper.utils.versioning import (
    check_copilot_helper_version_needs_update,
)


@click.group(chain=True, cls=ClickDocOptGroup)
def svc():
    """AWS Copilot svc actions with DBT extras."""
    check_copilot_helper_version_needs_update()


@svc.command()
@click.option("--env", type=str, required=True)
@click.option("--name", type=str, required=True)
@click.option("--image-tag", type=str, required=False, show_default=True, default="latest")
def deploy(env, name, image_tag):
    """Deploy image tag to a service, default to image tagged latest."""

    def get_commit_tag_for_latest_image():
        ecr_client = boto3.client("ecr")
        response = ecr_client.describe_images(
            registryId="854321987474",
            repositoryName="demodjango",
            imageIds=[
                {"imageTag": "latest"},
            ],
        )
        image_tags = response["imageDetails"][0]["imageTags"]
        filtered = filter(lambda tag: re.match("(commit{1}-[a-f0-9]{7,32})", tag), image_tags)
        return list(filtered)[0]

    if image_tag == "latest":
        image_tag = get_commit_tag_for_latest_image()

    command = f"IMAGE_TAG={image_tag} copilot svc deploy --env {env} --name {name}"
    print("Running:", command)
    subprocess.call(
        command,
        shell=True,
    )