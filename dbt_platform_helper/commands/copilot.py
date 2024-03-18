#!/usr/bin/env python

import copy
import json
from os import listdir
from os.path import isfile
from pathlib import Path
from pathlib import PosixPath

import click
import yaml

from dbt_platform_helper.utils.aws import SSM_BASE_PATH
from dbt_platform_helper.utils.aws import get_aws_session_or_abort
from dbt_platform_helper.utils.click import ClickDocOptGroup
from dbt_platform_helper.utils.files import ensure_cwd_is_repo_root
from dbt_platform_helper.utils.files import generate_override_files
from dbt_platform_helper.utils.files import mkfile
from dbt_platform_helper.utils.template import camel_case
from dbt_platform_helper.utils.template import setup_templates
from dbt_platform_helper.utils.validation import validate_addons
from dbt_platform_helper.utils.versioning import (
    check_platform_helper_version_needs_update,
)

PACKAGE_DIR = Path(__file__).resolve().parent.parent

WAF_ACL_ARN_KEY = "waf-acl-arn"

SERVICE_TYPES = [
    "Load Balanced Web Service",
    "Backend Service",
    "Request-Driven Web Service",
    "Static Site",
    "Worker Service",
]


def list_copilot_local_environments():
    return [
        path.parent.parts[-1] for path in Path("./copilot/environments/").glob("*/manifest.yml")
    ]


def is_service(path: PosixPath) -> bool:
    with open(path) as manifest_file:
        data = yaml.safe_load(manifest_file)
        if not data or not data.get("type"):
            click.echo(
                click.style(f"No type defined in manifest file {str(path)}; exiting", fg="red")
            )
            exit(1)

        return data.get("type") in SERVICE_TYPES


def list_copilot_local_services():
    return [
        path.parent.parts[-1]
        for path in Path("./copilot/").glob("*/manifest.yml")
        if is_service(path)
    ]


@click.group(chain=True, cls=ClickDocOptGroup)
def copilot():
    check_platform_helper_version_needs_update()


def _validate_and_normalise_config(config_file):
    """Load the addons.yaml file, validate it and return the normalised config
    dict."""

    def _lookup_plan(addon_type, env_conf):
        plan = env_conf.pop("plan", None)
        conf = addon_plans[addon_type][plan] if plan else {}

        # Make a copy of the addon plan config so subsequent
        # calls do not override the root object
        conf = conf.copy()

        conf.update(env_conf)

        return conf

    def _normalise_keys(source: dict):
        return {k.replace("-", "_"): v for k, v in source.items()}

    with open(PACKAGE_DIR / "addon-plans.yml", "r") as fd:
        addon_plans = yaml.safe_load(fd)

    # load and validate config
    with open(config_file, "r") as fd:
        config = yaml.safe_load(fd)

    # empty file
    if not config:
        return {}

    errors = validate_addons(config)
    if errors:
        click.echo(click.style(f"Errors found in {config_file}:", fg="red"))
        for addon, error in errors.items():
            click.echo(click.style(f"Addon '{addon}': {error}", fg="red"))
        exit(1)

    env_names = list_copilot_local_environments()
    svc_names = list_copilot_local_services()

    if not env_names:
        click.echo(
            click.style(f"No environments found in ./copilot/environments; exiting", fg="red")
        )
        exit(1)

    if not svc_names:
        click.echo(click.style(f"No services found in ./copilot/; exiting", fg="red"))
        exit(1)

    normalised_config = {}
    for addon_name, addon_config in config.items():
        addon_type = addon_config["type"]
        normalised_config[addon_name] = copy.deepcopy(addon_config)

        if "services" in normalised_config[addon_name]:
            if normalised_config[addon_name]["services"] == "__all__":
                normalised_config[addon_name]["services"] = svc_names

            if not set(normalised_config[addon_name]["services"]).issubset(set(svc_names)):
                click.echo(
                    click.style(
                        f"Services listed in {addon_name}.services do not exist in ./copilot/",
                        fg="red",
                    ),
                )
                exit(1)

        environments = normalised_config[addon_name].pop("environments", {})
        default = environments.pop("default", {})

        initial = _lookup_plan(addon_type, default)

        if not set(environments.keys()).issubset(set(env_names)):
            click.echo(
                click.style(
                    f"Environment keys listed in {addon_name} do not match ./copilot/environments",
                    fg="red",
                ),
            )
            exit(1)

        normalised_environments = {}

        for env in env_names:
            normalised_environments[env] = _normalise_keys(initial)

        for env_name, env_config in environments.items():
            normalised_environments[env_name].update(
                _lookup_plan(addon_type, _normalise_keys(env_config))
            )

        normalised_config[addon_name]["environments"] = normalised_environments

    return normalised_config


def get_log_destination_arn():
    """Get destination arns stored in param store in projects aws account."""
    session = get_aws_session_or_abort()
    client = session.client("ssm", region_name="eu-west-2")
    response = client.get_parameters(Names=["/copilot/tools/central_log_groups"])

    if not response["Parameters"]:
        click.echo(
            click.style(
                "No aws central log group defined in Parameter Store at location /copilot/tools/central_log_groups; exiting",
                fg="red",
            )
        )
        exit(1)

    destination_arns = json.loads(response["Parameters"][0]["Value"])
    return destination_arns


def _generate_svc_overrides(base_path, templates, name):
    click.echo(f"\n>>> Generating service overrides for {name}\n")
    overrides_path = base_path.joinpath(f"copilot/{name}/overrides")
    overrides_path.mkdir(parents=True, exist_ok=True)
    overrides_file = overrides_path.joinpath("cfn.patches.yml")
    overrides_file.write_text(templates.get_template("svc/overrides/cfn.patches.yml").render())


@copilot.command(deprecated=True, hidden=True)
def make_addons():
    """Generate addons CloudFormation for each environment."""
    output_dir = Path(".").absolute()

    ensure_cwd_is_repo_root()
    templates = setup_templates()
    config = _get_config()

    with open(PACKAGE_DIR / "addons-template-map.yml") as fd:
        addon_template_map = yaml.safe_load(fd)

    _generate_env_overrides(output_dir)

    click.echo("\n>>> Generating addons CloudFormation\n")

    env_addons_path = Path(f"copilot/environments/addons/")
    (output_dir / env_addons_path).mkdir(parents=True, exist_ok=True)

    _cleanup_old_files(config, output_dir, env_addons_path)
    custom_resources = _get_custom_resources()

    svc_names = list_copilot_local_services()
    base_path = Path(".")
    for svc_name in svc_names:
        _generate_svc_overrides(base_path, templates, svc_name)

    services = []
    has_addons_parameters = False
    has_postgres_addon = False
    for addon_name, addon_config in config.items():
        print(f">>>>>>>>> {addon_name}")
        addon_type = addon_config.pop("type")
        environments = addon_config.pop("environments")
        if addon_template_map[addon_type].get("requires_addons_parameters", False):
            has_addons_parameters = True
        if addon_type in ["aurora-postgres", "rds-postgres"]:
            has_postgres_addon = True

        for environment_name, environment_config in environments.items():
            if not environment_config.get("deletion_policy"):
                environments[environment_name]["deletion_policy"] = addon_config.get(
                    "deletion_policy", "Delete"
                )

        environment_addon_config = {
            "addon_type": addon_type,
            "custom_resources": custom_resources,
            "environments": environments,
            "name": addon_config.get("name", None) or addon_name,
            "prefix": camel_case(addon_name),
            "secret_name": addon_name.upper().replace("-", "_"),
            **addon_config,
        }

        services.append(environment_addon_config)

        service_addon_config = {
            "name": addon_config.get("name", None) or addon_name,
            "prefix": camel_case(addon_name),
            "environments": environments,
            "custom_resources": custom_resources,
            **addon_config,
        }

        if has_postgres_addon:
            service_addon_config["type"] = addon_type.split("-")[0]

        log_destination_arns = get_log_destination_arn()

        if addon_type in ["s3", "s3-policy"]:
            service_addon_config["kms_key_reference"] = service_addon_config["prefix"].rsplit(
                "BucketAccess", 1
            )[0]

        _generate_env_addons(
            addon_name,
            addon_template_map,
            config.items(),
            env_addons_path,
            environment_addon_config,
            output_dir,
            templates,
            log_destination_arns,
        )
        _generate_service_addons(
            addon_config,
            addon_name,
            addon_template_map,
            addon_type,
            output_dir,
            service_addon_config,
            templates,
            log_destination_arns,
        )

        if addon_type in ["aurora-postgres", "rds-postgres"]:
            click.secho(
                "\nNote: The key DATABASE_CREDENTIALS may need to be changed to match your Django settings configuration.",
                fg="yellow",
            )

    if has_addons_parameters:
        template = templates.get_template("addons/env/addons.parameters.yml")
        contents = template.render({"has_postgres_addon": has_postgres_addon})
        click.echo(
            mkfile(output_dir, env_addons_path / "addons.parameters.yml", contents, overwrite=True)
        )

    click.echo(templates.get_template("addon-instructions.txt").render(services=services))


def _get_config():
    config = _validate_and_normalise_config(PACKAGE_DIR / "default-addons.yml")
    project_config = _validate_and_normalise_config("addons.yml")
    config.update(project_config)
    return config


def _generate_env_overrides(output_dir):
    click.echo("\n>>> Generating Environment overrides\n")
    overrides_path = output_dir.joinpath(f"copilot/environments/overrides")
    overrides_path.mkdir(parents=True, exist_ok=True)
    template_overrides_path = Path(__file__).parent.parent.joinpath("templates/env/overrides")
    generate_override_files(Path("."), template_overrides_path, overrides_path)


def _generate_env_addons(
    addon_name,
    addon_template_map,
    addons,
    env_addons_path,
    environment_addon_config,
    output_dir,
    templates,
    log_destination_arns,
):
    # generate env addons
    addon_type = environment_addon_config["addon_type"]
    for addon in addon_template_map[addon_type].get("env", []):
        template = templates.get_template(addon["template"])
        contents = template.render(
            {
                "addon_config": environment_addon_config,
                "addons": addons,
                "log_destination": log_destination_arns,
            }
        )

        filename = addon.get("filename", f"{addon_name}.yml")

        click.echo(mkfile(output_dir, env_addons_path / filename, contents, overwrite=True))


def _generate_service_addons(
    addon_config,
    addon_name,
    addon_template_map,
    addon_type,
    output_dir,
    service_addon_config,
    templates,
    log_destination_arns,
):
    # generate svc addons
    for addon in addon_template_map[addon_type].get("svc", []):
        template = templates.get_template(addon["template"])

        for svc in addon_config.get("services", []):
            service_path = Path(f"copilot/{svc}/addons/")

            contents = template.render(
                {
                    "addon_config": service_addon_config,
                    "log_destination": log_destination_arns,
                }
            )

            filename = addon.get("filename", f"{addon_name}.yml")

            (output_dir / service_path).mkdir(parents=True, exist_ok=True)
            click.echo(mkfile(output_dir, service_path / filename, contents, overwrite=True))


def _get_custom_resources():
    custom_resources = {}
    custom_resource_path = (Path(__file__).parent / "../custom_resources/").resolve()
    for file in listdir(custom_resource_path):
        file_path = custom_resource_path / file
        if isfile(file_path) and file_path.name.endswith(".py") and file_path.name != "__init__.py":
            custom_resource_contents = file_path.read_text()

            def file_with_formatting_options(padding=0, contents=custom_resource_contents):
                lines = [
                    (" " * padding) + line if line.strip() else line.strip()
                    for line in contents.splitlines(True)
                ]
                return "".join(lines)

            custom_resources[file_path.name.rstrip(".py")] = file_with_formatting_options
    return custom_resources


def _cleanup_old_files(config, output_dir, env_addons_path):
    for f in (output_dir / env_addons_path).iterdir():
        if f.is_file():
            f.unlink()

    all_services = set()
    for services in [v["services"] for v in config.values() if "services" in v]:
        all_services.update(services)

    for service in all_services:
        svc_addons_dir = Path(output_dir, "copilot", service, "addons")
        if not svc_addons_dir.exists():
            continue
        for f in svc_addons_dir.iterdir():
            if f.is_file():
                f.unlink()


@copilot.command()
@click.argument("app", type=str, required=True)
@click.argument("env", type=str, required=True)
def get_env_secrets(app, env):
    """List secret names and values for an environment."""

    session = get_aws_session_or_abort()
    client = session.client("ssm")

    path = SSM_BASE_PATH.format(app=app, env=env)

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
