#!/usr/bin/env python

from collections import defaultdict
from pathlib import Path
import re
import sys

import boto3
import click
from cloudfoundry_client.client import CloudFoundryClient
import jinja2
from schema import Optional, Schema, SchemaError, Use
import yaml


SSM_BASE_PATH = "/copilot/{app}/{env}/secrets/"
SSM_PATH = "/copilot/{app}/{env}/secrets/{name}"


config_schema = Schema({
    "app": str,
    "domain": str,
    "environments": {
        str: {
            Optional("certificate_arns"): [str]
        }
    },
    "services": [
        {
            "name": str,
            "type": lambda s: s in ("public", "backend",),
            "repo": str,
            "image_location": str,
            "command": str,
            Optional("notes"): str,
            Optional("secrets_from"): str,
            "environments": {
                str: {
                    "paas": str,
                    Optional("url"): str,
                    Optional("ipfilter"): bool,
                }
            },
            "backing-services": [
                {
                    "name": str,
                    "type": lambda s: s in ("s3", "external-s3", "postgres", "redis", "opensearch",),
                    Optional("paas-description"): str,
                    Optional("paas-instance"): str,
                    Optional("notes"): str,
                    Optional("bucket_name"): str,           # for external-s3 type
                    Optional("readonly"): bool,             # for external-s3 type
                    Optional("shared"): bool,
                }
            ],
            Optional("overlapping_secrets"): [ str ],
            "secrets": {
                Optional(str): str,
            },
            "env_vars": {
                Optional(str): str,
            },
        }
    ],
})

storage_schema = Schema({
    str: {
         "type": lambda s: s in ("s3", "external-s3", "postgres", "redis", "opensearch",),
         str: {
            Optional("plan"): str,
            # s3
            Optional("bucket-name"): str,
            Optional("readonly"): bool,
            # redis
            Optional("engine"): str,
            Optional("replicas"): int,
            Optional("instance"): str,
            # opensearch
            Optional("volume-size"): int,
            Optional("instances"): int,
            Optional("master"): bool,
            Optional("instance"): str,
            # Aurora PG
            Optional("min-capacity"): Use(float),
            Optional("max-capacity"): Use(float),
         }
    }
})


def _mkdir(base, path):

    if (base / path).exists():
        return f"directory {path} exists; doing nothing"

    (base / path).mkdir(parents=True)
    return f"directory {path} created"


def _mkfile(base, path, contents, overwrite=False):

    file_exists = (base / path).exists()

    if file_exists and not overwrite:        
        return f"file {path} exists; doing nothing"

    action = "overwritten" if overwrite else "created"

    with open(base / path, "w") as fd:
        fd.write(contents)

    return f"file {path} {action}"


def camel_case(s):
    s = re.sub(r"(_|-)+", " ", s).title().replace(" ", "")
    return ''.join([s[0].lower(), s[1:]])


def get_paas_env_vars(client, paas):

    org, space, app = paas.split("/")

    env_vars = None

    for paas_org in client.v2.organizations:
        if paas_org["entity"]["name"] == org:
            for paas_space in paas_org.spaces():
                if paas_space["entity"]["name"] == space:
                    for paas_app in paas_space.apps():
                        if paas_app["entity"]["name"] == app:
                            env_vars = paas_app["entity"]["environment_json"]

    if not env_vars:
        raise Exception(f"Application {paas} not found")

    return dict(env_vars)


def setup_templates():
    template_path = Path(__file__).parent / Path("templates")
    templateLoader = jinja2.FileSystemLoader(searchpath=template_path)
    templateEnv = jinja2.Environment(loader=templateLoader)

    templates = {
        "instructions": templateEnv.get_template("instructions.txt"),
        "storage-instructions": templateEnv.get_template("storage-instructions.txt"),
        "svc": {
            "public-manifest": templateEnv.get_template("svc/manifest-public.yml"),
            "backend-manifest": templateEnv.get_template("svc/manifest-backend.yml"),
            "opensearch": templateEnv.get_template("svc/addons/opensearch.yml"),
            "postgres": templateEnv.get_template("svc/addons/postgres.yml"),
            "redis": templateEnv.get_template("svc/addons/redis.yml"),
            "s3": templateEnv.get_template("svc/addons/s3.yml"),
            "external-s3": templateEnv.get_template("svc/addons/external-s3.yml"),
        },
        "env": {
            "manifest": templateEnv.get_template("env/manifest.yml"),
            "opensearch": templateEnv.get_template("env/addons/opensearch.yml"),
            "postgres": templateEnv.get_template("env/addons/postgres.yml"),
            "redis": templateEnv.get_template("env/addons/redis-cluster.yml"),
            "s3": templateEnv.get_template("env/addons/s3.yml"),
            "external-s3": templateEnv.get_template("env/addons/external-s3.yml"),
        },
    }

    return templates


def load_and_validate_config(path):

    with open(path, "r") as fd:
        conf = yaml.safe_load(fd)

    # validate the file
    schema = Schema(config_schema)
    config = schema.validate(conf)

    return config


def set_ssm_param(app, env, param_name, param_value, overwrite, exists):
    client = boto3.client('ssm')
    args = dict(
        Name=param_name,
        Description='copied from cloudfoundry',
        Value=param_value,
        Type='SecureString',
        Overwrite=overwrite,
        Tags=[
                {
                    'Key': 'copilot-application',
                    'Value': app
                },
                {
                    'Key': 'copilot-environment',
                    'Value': env
                },
        ],
    )

    if overwrite and exists:
        # Tags can't be updated when overwriting
        del args["Tags"]

    response = client.put_parameter(**args)


def get_ssm_secret_names(app, env):
    client = boto3.client('ssm')

    path = SSM_BASE_PATH.format(app=app, env=env)

    params = dict(
        Path=path,
        Recursive=False,
        WithDecryption=True,
        MaxResults=10,
    )

    secret_names = []

    while True:
        response = client.get_parameters_by_path(
            **params
        )

        for secret in response["Parameters"]:
            secret_names.append(secret["Name"])

        if "NextToken" in response:
            params["NextToken"] = response["NextToken"]
        else:
            break

    return sorted(secret_names)


@click.group()
def cli():
    pass


@cli.command()
@click.argument("config-file", type=click.Path(exists=True))
@click.argument("output", type=click.Path(exists=True), default=".")
def make_config(config_file, output):
    """
    Generate copilot boilerplate code

    CONFIG-FILE is the path to the input yaml config file
    OUTPUT is the location of the repo root dir. Defaults to the current directory.
    """

    base_path = Path(output)
    config = load_and_validate_config(config_file)

    templates = setup_templates()

    click.echo("GENERATING COPILOT CONFIG FILES")

    # create copilot directory
    click.echo(_mkdir(base_path, "copilot"))

    # create copilot/.workspace file
    contents = "application: {}".format(config["app"])
    click.echo(_mkfile(base_path, "copilot/.workspace", contents))

    # create copilot/environments directory
    click.echo(_mkdir(base_path, "copilot/environments"))

    # create each environment directory and manifest.yml
    for name, env in config["environments"].items():
        click.echo(_mkdir(base_path, f"copilot/environments/{name}"))
        contents = templates["env"]["manifest"].render({
            "name": name,
            "certificate_arn": env["certificate_arns"][0] if "certificate_arns" in env else ""
        })
        click.echo(_mkfile(base_path, f"copilot/environments/{name}/manifest.yml", contents))

    # create each service directory and manifest.yml
    for service in config["services"]:
        service["ipfilter"] = any(env.get("ipfilter", False) for _, env in service["environments"].items())
        name = service["name"]
        click.echo(_mkdir(base_path, f"copilot/{name}/addons/"))

        if "secrets_from" in service:
            # Copy secrets from the app referredd to in the "secrets_from" key
            related_service = [s for s in config["services"] if s["name"] == service["secrets_from"]][0]

            service["secrets"].update(related_service["secrets"])

        contents = templates["svc"][service["type"] + "-manifest"].render(service)

        click.echo(_mkfile(base_path, f"copilot/{name}/manifest.yml", contents))

        for bs in service["backing-services"]:
            bs["prefix"] = camel_case(name + "-" + bs["name"])

            contents = templates["svc"][bs["type"]].render(dict(service=bs))
            _mkfile(base_path, f"copilot/{name}/addons/{bs['name']}.yml", contents)

    # generate instructions
    config["config_file"] = config_file
    instructions = templates["instructions"].render(config)
    click.echo("---")
    click.echo(instructions)


@cli.command()
@click.argument("config-file", type=click.Path(exists=True))
@click.option('--env', help='Migrate secrets from a specific environment')
@click.option('--svc', help='Migrate secrets from a specific service')
@click.option('--overwrite', is_flag=True, show_default=True, default=False, help='Overwrite existing secrets?')
@click.option('--dry-run', is_flag=True, show_default=True, default=False, help='dry run')
def migrate_secrets(config_file, env, svc, overwrite, dry_run):
    """
    Migrate secrets from your gov paas application to AWS/copilot

    You need to be authenticated via cf cli and the AWS cli to use this commmand.

    If you're using AWS profiles, use the AWS_PROFILE env var to indicate the which profile to use, e.g.:

    AWS_PROFILE=myaccount copilot-bootstrap.py ...
    """

    # TODO: optional SSM or secret manager

    cf_client = CloudFoundryClient.build_from_cf_config()
    config = load_and_validate_config(config_file)

    if env and env not in config["environments"].keys():
        raise click.ClickException(f"{env} is not an environment in {config_file}")

    if svc and svc not in config["services"].keys():
        raise click.ClickException(f"{svc} is not a servuce in {config_file}")

    existing_ssm_data = defaultdict(list)
    for env_name, _ in config["environments"].items():
        if env and env_name != env:
            continue

        existing_ssm_data[env_name] = get_ssm_secret_names(config["app"], env_name)

    # get the secrets from the paas
    for service in config["services"]:
        service_name = service["name"]
        secrets = service["secrets"]

        if svc and service["name"] != svc:
            continue

        if "secrets_from" in service:
            click.echo(f"{service_name} shares secrets with {service['secrets_from']}; skipping")
            continue

        for env_name, environment in service["environments"].items():

            if env and env_name != env:
                continue

            click.echo("-----------------")
            click.echo(f">>> migrating secrets fro service: {service_name}; environment: {env_name}")

            click.echo(f"getting env vars for from {environment['paas']}")
            env_vars = get_paas_env_vars(cf_client, environment["paas"])

            click.echo("Transfering secrets ...")
            for app_secret_key, ssm_secret_key in secrets.items():
                ssm_path = SSM_PATH.format(app=config["app"], env=env_name, name=ssm_secret_key)

                if app_secret_key not in env_vars:
                    # NOT FOUND
                    param_value = "NOT FOUND"
                    click.echo(f"Key not found in paas app: {app_secret_key}; setting to 'NOT FOUND'")
                elif not env_vars[app_secret_key]:
                    # FOUND BUT EMPTY STRING
                    param_value = "EMPTY"
                    click.echo(f"Empty env var in paas app: {app_secret_key}; SSM requires a non-empty string; setting to 'EMPTY'")
                else:
                    param_value = env_vars[app_secret_key]

                param_exists = ssm_path in existing_ssm_data[env_name]

                if overwrite or not param_exists:
                    if not dry_run:
                        set_ssm_param(config["app"], env_name, ssm_path, param_value, overwrite, param_exists)

                    if not param_exists:
                        existing_ssm_data[env_name].append(ssm_path)

                text = "Created" if not param_exists else "Overwritten" if overwrite else "NOT overwritten"

                click.echo(f"{text} {ssm_path}")


@cli.command()
@click.argument("config-file", type=click.Path(exists=True))
def instructions(config_file):
    """
    Show migration instructions
    """
    templates = setup_templates()

    config = load_and_validate_config(config_file)
    config["config_file"] = config_file

    instructions = templates["instructions"].render(config)

    click.echo(instructions)


@cli.command()
@click.argument("storage-config-file", type=click.Path(exists=True))
@click.argument("output", type=click.Path(exists=True), default=".")
@click.option('--overwrite', is_flag=True, show_default=True, default=True, help='Overwrite existing cloudformation? Defaults to True')
def generate_storage(storage_config_file, output, overwrite):
    """
    Generate storage cloudformation for each environment
    """

    with open(Path(__file__).parent / Path("storage-plans.yaml"), "r") as fd:
        storage_plans = yaml.safe_load(fd)

    templates = setup_templates()

    # load and validate config 
    with open(storage_config_file, "r") as fd:
        conf = yaml.safe_load(fd)

    # validate the file
    schema = Schema(storage_schema)
    config = schema.validate(conf)

    if not Path("./copilot").exists() or not Path("./copilot").is_dir():
        click.echo("Cannot find copilot directory. Run this command in the root of the deployment repository.")

    env_names = [path.parent.parts[-1] for path in Path("./copilot/environments/").glob("*/manifest.yml")]

    env_config = {}

    path = Path(f"copilot/environments/addons/")
    click.echo( _mkdir(output, path))

    def _lookup_plan(storage_type, env_conf):
        plan = env_conf.pop("plan", None)
        conf = storage_plans[storage_type][plan] if plan else {}
        conf.update(env_conf)

        return conf

    services = []

    for storage_name, storage_config in config.items():
        storage_type = storage_config.pop("type")
        initial = _lookup_plan(storage_type, storage_config.pop("default", {}))

        template = templates["env"][storage_type]

        for env in env_names:
            env_config[env] = {k.replace("-", "_"): v for k, v in initial.items()}

        for name, env in storage_config.items():
            env_config[name].update(
                _lookup_plan(storage_type, env)
            )

        service = {
            "secret_name": storage_name.upper().replace("-", "_"),
            "name": storage_name,
            "environments": env_config,
            "prefix": camel_case(storage_name),
            "storage_type": storage_type,
        }

        contents = template.render({
            "service": service
        })

        services.append(service)

        click.echo(_mkfile(output, path / f"{storage_name}.yml", contents, overwrite=overwrite))

    click.echo(templates["storage-instructions"].render(services=services))


@cli.command()
@click.argument("service_name", type=str)
@click.argument("env", type=str, default="prod")
def get_service_secrets(service_name, env):
    """
    List secret names and values for a service
    """
    
    if not Path("./copilot").exists() or not Path("./copilot").is_dir():
        click.echo("Cannot find copilot directory. Run this command in the root of the deployment repository.")
        
    client = boto3.client('ssm')

    path = SSM_BASE_PATH.format(app=service_name, env=env)

    params = dict(
        Path=path,
        Recursive=False,
        WithDecryption=True,
        MaxResults=10
    )
    secrets = []
    
    # TODO: refactor shared code with get_ssm_secret_names
    while True:
        response = client.get_parameters_by_path(
            **params
        )

        for secret in response["Parameters"]:
            secrets.append("{:<8}: {:<15}".format(secret["Name"], secret["Value"]))

        if "NextToken" in response:
            params["NextToken"] = response["NextToken"]
        else:
            break
    
    print("\n".join(sorted(secrets)))
   

if __name__ == "__main__":
    cli()
