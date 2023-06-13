#!/usr/bin/env python

import copy
import json
from pathlib import Path

import boto3
import click
import yaml
from jsonschema import validate as validate_json

from .utils import SSM_BASE_PATH
from .utils import camel_case
from .utils import ensure_cwd_is_repo_root
from .utils import mkdir
from .utils import mkfile
from .utils import setup_templates

BASE_DIR = Path(__file__).parent.parent

WAF_ACL_ARN_KEY = "waf-acl-arn"


def list_copilot_local_environments():
    return [path.parent.parts[-1] for path in Path("./copilot/environments/").glob("*/manifest.yml")]


def list_copilot_local_services():
    return [path.parent.parts[-1] for path in Path("./copilot/").glob("*/manifest.yml")]


@click.group()
def copilot():
    pass


def _validate_and_normalise_config(config_file):
    """Load the storage.yaml file, validate it and return the normalised config
    dict."""

    def _lookup_plan(storage_type, env_conf):
        plan = env_conf.pop("plan", None)
        conf = storage_plans[storage_type][plan] if plan else {}
        conf.update(env_conf)

        return conf

    def _normalise_keys(source: dict):
        return {k.replace("-", "_"): v for k, v in source.items()}

    with open(BASE_DIR / "storage-plans.yml", "r") as fd:
        storage_plans = yaml.safe_load(fd)

    with open(BASE_DIR / "schemas/storage-schema.json", "r") as fd:
        schema = json.load(fd)

    # load and validate config
    with open(config_file, "r") as fd:
        config = yaml.safe_load(fd)

    # empty file
    if not config:
        return {}

    validate_json(instance=config, schema=schema)

    env_names = list_copilot_local_environments()
    svc_names = list_copilot_local_services()

    if not env_names:
        click.echo(click.style(f"No environments found in ./copilot/environments; exiting", fg="red"))
        exit(1)

    if not svc_names:
        click.echo(click.style(f"No services found in ./copilot/; exiting", fg="red"))
        exit(1)

    normalised_config = {}
    for storage_name, storage_config in config.items():
        storage_type = storage_config["type"]
        normalised_config[storage_name] = copy.deepcopy(storage_config)

        if "services" in normalised_config[storage_name]:
            if type(normalised_config[storage_name]["services"]) == str:
                if normalised_config[storage_name]["services"] == "__all__":
                    normalised_config[storage_name]["services"] = svc_names
                else:
                    click.echo(
                        click.style(f"{storage_name}.services must be a list of service names or '__all__'", fg="red"),
                    )
                    exit(1)

            if not set(normalised_config[storage_name]["services"]).issubset(set(svc_names)):
                click.echo(
                    click.style(f"Services listed in {storage_name}.services do not exist in ./copilot/", fg="red"),
                )
                exit(1)

        environments = normalised_config[storage_name].pop("environments", {})
        default = environments.pop("default", {})

        initial = _lookup_plan(storage_type, default)

        if not set(environments.keys()).issubset(set(env_names)):
            click.echo(
                click.style(
                    f"Environment keys listed in {storage_name} do not match ./copilot/environments",
                    fg="red",
                ),
            )
            exit(1)

        normalised_environments = {}

        for env in env_names:
            normalised_environments[env] = _normalise_keys(initial)

        for env_name, env_config in environments.items():
            normalised_environments[env_name].update(_lookup_plan(storage_type, _normalise_keys(env_config)))

        normalised_config[storage_name]["environments"] = normalised_environments

    return normalised_config


@copilot.command()
@click.argument("storage-config-file", type=click.Path(exists=True))
def make_storage(storage_config_file):
    """Generate storage cloudformation for each environment."""

    overwrite = True
    output_dir = Path(".").absolute()

    ensure_cwd_is_repo_root()

    templates = setup_templates()

    config = _validate_and_normalise_config(BASE_DIR / "default-storage.yml")

    project_config = _validate_and_normalise_config(storage_config_file)

    config.update(project_config)

    click.echo("\n>>> Generating storage cloudformation\n")

    path = Path(f"copilot/environments/addons/")
    mkdir(output_dir, path)

    services = []
    for storage_name, storage_config in config.items():
        storage_type = storage_config.pop("type")
        environments = storage_config.pop("environments")

        service = {
            "secret_name": storage_name.upper().replace("-", "_"),
            "name": storage_config.get("name", None) or storage_name,
            "environments": environments,
            "prefix": camel_case(storage_name),
            "storage_type": storage_type,
            **storage_config,
        }

        services.append(service)

        # s3-policy only applies to individual services
        if storage_type != "s3-policy":
            template = templates["env"][storage_type]
            contents = template.render({"service": service})

            click.echo(mkfile(output_dir, path / f"{storage_name}.yml", contents, overwrite=overwrite))

        # s3 buckets require additional service level cloudformation to grant the ECS task role access to the bucket
        if storage_type in ["s3", "s3-policy"]:
            template = templates["svc"]["s3-policy"]

            for svc in storage_config.get("services", []):
                service_path = Path(f"copilot/{svc}/addons/")

                service = {
                    "name": storage_config.get("name", None) or storage_name,
                    "prefix": camel_case(storage_name),
                    "environments": environments,
                    **storage_config,
                }

                contents = template.render({"service": service})

                mkdir(output_dir, service_path)
                click.echo(mkfile(output_dir, service_path / f"{storage_name}.yml", contents, overwrite=overwrite))

    click.echo(templates["storage-instructions"].render(services=services))


@copilot.command()
def apply_waf():
    """Apply the WAF environment addon."""

    templates = setup_templates()
    overwrite = True

    ensure_cwd_is_repo_root()

    env_names = list_copilot_local_environments()

    if not env_names:
        click.secho(f"Cannot add WAF CFN templates: No environments found in ./copilot/environments/", fg="red")
        exit(1)

    def _validate_arn(arn):
        return arn and arn.startswith("arn:aws:wafv2:")

    arns = {}

    for name in env_names:
        with open(f"./copilot/environments/{name}/manifest.yml", "r") as fd:
            config = yaml.safe_load(fd)

        arns[name] = config.get(WAF_ACL_ARN_KEY) if config else None

    if not all(_validate_arn(arn) for arn in arns.values()):
        click.secho(
            f"Cannot add WAF CFN templates: Set a valid `{WAF_ACL_ARN_KEY}` in each ./copilot/environments/*/manifest.yml file",
            fg="red",
        )
        exit(1)

    # create the addons dir if it doesn't already exist
    path = Path("./copilot/environments/addons")
    mkdir(".", path)

    # create the ./copilot/environments/addons/addons.parameters.yml file
    contents = templates["env"]["parameters"].render({})
    click.echo(mkfile(".", path / "addons.parameters.yml", contents, overwrite=overwrite))

    # create the ./copilot/environments/addons/waf.yml file
    contents = templates["env"]["waf"].render({"arns": arns})

    click.echo(mkfile(".", path / "waf.yml", contents, overwrite=overwrite))


@copilot.command()
@click.argument("service_name", type=str)
@click.argument("env", type=str, default="prod")
def get_service_secrets(service_name, env):
    """List secret names and values for a service."""

    ensure_cwd_is_repo_root()

    client = boto3.client("ssm")

    path = SSM_BASE_PATH.format(app=service_name, env=env)

    params = dict(Path=path, Recursive=False, WithDecryption=True, MaxResults=10)
    secrets = []

    # TODO: refactor shared code with get_ssm_secret_names
    while True:
        response = client.get_parameters_by_path(**params)

        for secret in response["Parameters"]:
            secrets.append(f"{secret['Name']:<8}: {secret['Value']:<15}")

        if "NextToken" in response:
            params["NextToken"] = response["NextToken"]
        else:
            break

    print("\n".join(sorted(secrets)))
