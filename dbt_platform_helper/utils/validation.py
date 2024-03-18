import ipaddress
import re

import click
from botocore.exceptions import ClientError
from schema import Optional
from schema import Or
from schema import Regex
from schema import Schema
from schema import SchemaError

from dbt_platform_helper.utils.aws import get_aws_session_or_abort


def validate_string(regex_pattern: str):
    def validator(string):
        if not re.match(regex_pattern, string):
            raise SchemaError(
                f"String '{string}' does not match the required pattern '{regex_pattern}'. For more details on valid string patterns see: https://aws.github.io/copilot-cli/docs/manifest/lb-web-service/"
            )
        return string

    return validator


S3_BUCKET_NAME_ERROR_TEMPLATE = "Bucket name '{}' is invalid:\n{}"
AVAILABILITY_UNCERTAIN_TEMPLATE = (
    "Warning: Could not determine the availability of bucket name '{}'."
)
BUCKET_NAME_IN_USE_TEMPLATE = "Warning: Bucket name '{}' is already in use. Check your AWS accounts to see if this is a problem."


def warn_on_s3_bucket_name_availability(name: str):
    """
    We try to find the bucket name in AWS.

    The validation logic is:
    True: if the response is a 200 (it exists and you have access - this bucket has probably already been deployed)
    True: if the response is a 404 (it could not be found)
    False: if the response is 40x (the bucket exists but you have no permission)
    """
    session = get_aws_session_or_abort()
    client = session.client("s3")
    try:
        client.head_bucket(Bucket=name)
        return
    except ClientError as ex:
        if "Error" not in ex.response or not "Code" in ex.response["Error"]:
            click.secho(AVAILABILITY_UNCERTAIN_TEMPLATE.format(name), fg="yellow")
            return
        if ex.response["Error"]["Code"] == "404":
            return
        if int(ex.response["Error"]["Code"]) > 499:
            click.secho(AVAILABILITY_UNCERTAIN_TEMPLATE.format(name), fg="yellow")
            return

    click.secho(BUCKET_NAME_IN_USE_TEMPLATE.format(name), fg="yellow")


def validate_s3_bucket_name(name: str):
    errors = []
    if not (2 < len(name) < 64):
        errors.append("Length must be between 3 and 63 characters inclusive.")

    if not re.match(r"^[a-z0-9].*[a-z0-9]$", name):
        errors.append("Names must start and end with 0-9 or a-z.")

    if not re.match(r"^[a-z0-9.-]*$", name):
        errors.append("Names can only contain the characters 0-9, a-z, '.' and '-'.")

    if ".." in name:
        errors.append("Names cannot contain two adjacent periods.")

    try:
        ipaddress.ip_address(name)
        errors.append("Names cannot be IP addresses.")
    except ValueError:
        pass

    for prefix in ("xn--", "sthree-"):
        if name.startswith(prefix):
            errors.append(f"Names cannot be prefixed '{prefix}'.")

    for suffix in ("-s3alias", "--ol-s3"):
        if name.endswith(suffix):
            errors.append(f"Names cannot be suffixed '{suffix}'.")

    if not errors:
        # Don't waste time calling AWS if the bucket name is not even valid.
        warn_on_s3_bucket_name_availability(name)

    if errors:
        raise SchemaError(
            S3_BUCKET_NAME_ERROR_TEMPLATE.format(name, "\n".join(f"  {e}" for e in errors))
        )

    return True


def validate_addons(addons: dict):
    """
    Validate the addons file and return a dictionary of addon: error message.
    """
    errors = {}

    for addon_name, addon in addons.items():
        try:
            addon_type = addon.get("type", None)
            if not addon_type:
                errors[addon_name] = f"Missing addon type in addon '{addon_name}'"
                continue
            schema = SCHEMA_MAP.get(addon_type, None)
            if not schema:
                errors[addon_name] = (
                    f"Unsupported addon type '{addon_type}' in addon '{addon_name}'"
                )
                continue
            schema.validate(addon)
        except SchemaError as ex:
            errors[addon_name] = f"Error in {addon_name}: {ex.code}"

    return errors


def int_between(lower, upper):
    def is_between(value):
        if isinstance(value, int) and lower <= value <= upper:
            return True
        raise SchemaError(f"should be an integer between {lower} and {upper}")

    return is_between


def float_between_with_halfstep(lower, upper):
    def is_between(value):
        is_number = isinstance(value, int) or isinstance(value, float)
        is_half_step = re.match(r"^\d+(\.[05])?$", str(value))

        if is_number and is_half_step and lower <= value <= upper:
            return True
        raise SchemaError(f"should be a number between {lower} and {upper} in increments of 0.5")

    return is_between


ENV_NAME = Regex(
    r"^[a-zA-Z][a-zA-Z0-9]*$",
    error="Environment name {} is invalid: names must only contain alphanumeric characters.",
    # For values the "error" parameter works and outputs the custom text. For keys the custom text doesn't get reported in the exception for some reason.
)

range_validator = validate_string(r"^\d+-\d+$")
seconds_validator = validate_string(r"^\d+s$")

BOOTSTRAP_SCHEMA = Schema(
    {
        "app": str,
        "environments": {str: {Optional("certificate_arns"): [str]}},
        "services": [
            {
                "name": str,
                "type": lambda s: s
                in (
                    "public",
                    "backend",
                ),
                "repo": str,
                "image_location": str,
                Optional("notes"): str,
                Optional("secrets_from"): str,
                "environments": {
                    str: {
                        "paas": str,
                        Optional("url"): str,
                        Optional("ipfilter"): bool,
                        Optional("memory"): int,
                        Optional("count"): Or(
                            int,
                            {
                                # https://aws.github.io/copilot-cli/docs/manifest/lb-web-service/#count
                                "range": range_validator,  # e.g. 1-10
                                Optional("cooldown"): {
                                    "in": seconds_validator,  # e.g 30s
                                    "out": seconds_validator,  # e.g 30s
                                },
                                Optional("cpu_percentage"): int,
                                Optional("memory_percentage"): Or(
                                    int,
                                    {
                                        "value": int,
                                        "cooldown": {
                                            "in": seconds_validator,  # e.g. 80s
                                            "out": seconds_validator,  # e.g 160s
                                        },
                                    },
                                ),
                                Optional("requests"): int,
                                Optional("response_time"): seconds_validator,  # e.g. 2s
                            },
                        ),
                    },
                },
                Optional("backing_services"): [
                    {
                        "name": str,
                        "type": lambda s: s
                        in (
                            "s3",
                            "s3-policy",
                            "aurora-postgres",
                            "rds-postgres",
                            "redis",
                            "opensearch",
                        ),
                        Optional("paas_description"): str,
                        Optional("paas_instance"): str,
                        Optional("notes"): str,
                        Optional("bucket_name"): str,  # for external-s3 type
                        Optional("readonly"): bool,  # for external-s3 type
                        Optional("shared"): bool,
                    },
                ],
                Optional("overlapping_secrets"): [str],
                "secrets": {
                    Optional(str): str,
                },
                "env_vars": {
                    Optional(str): str,
                },
            },
        ],
    },
)

PIPELINES_SCHEMA = Schema(
    {
        Optional("accounts"): list[str],
        Optional("environments"): [
            {
                "name": str,
                Optional("requires_approval"): bool,
            },
        ],
        Optional("codebases"): [
            {
                "name": str,
                "repository": str,
                Optional("additional_ecr_repository"): str,
                "services": list[str],
                "pipelines": [
                    Or(
                        {
                            "name": str,
                            "branch": str,
                            "environments": [
                                {
                                    "name": str,
                                    Optional("requires_approval"): bool,
                                }
                            ],
                        },
                        {
                            "name": str,
                            "tag": bool,
                            "environments": [
                                {
                                    "name": str,
                                    Optional("requires_approval"): bool,
                                }
                            ],
                        },
                    ),
                ],
            },
        ],
    },
)

NUMBER = Or(int, float)
DB_DELETION_POLICY = Or("Delete", "Retain", "Snapshot")
DELETION_POLICY = Or("Delete", "Retain")
DELETION_PROTECTION = bool
RDS_PLANS = Or(
    "tiny", "small", "small-ha", "medium", "medium-ha", "large", "large-ha", "x-large", "x-large-ha"
)

RETENTION_POLICY = Or(
    None,
    {
        "mode": Or("GOVERNANCE", "COMPLIANCE"),
        Or("days", "years", only_one=True): int,
    },
)

REDIS_PLANS = Or(
    "micro",
    "micro-ha",
    "tiny",
    "tiny-ha",
    "small",
    "small-ha",
    "medium",
    "medium-ha",
    "large",
    "large-ha",
    "x-large",
    "x-large-ha",
)

REDIS_ENGINE_VERSIONS = Or("4.0.10", "5.0.6", "6.0", "6.2")

OPENSEARCH_PLANS = Or(
    "tiny", "small", "small-ha", "medium", "medium-ha", "large", "large-ha", "x-large", "x-large-ha"
)

OPENSEARCH_ENGINE_VERSIONS = Or("2.5", "2.3", "1.3", "1.2", "1.1", "1.0")

S3_BASE = {
    Optional("readonly"): bool,
    Optional("services"): Or("__all__", [str]),
    Optional("environments"): {
        ENV_NAME: {
            "bucket_name": validate_s3_bucket_name,
            Optional("deletion_policy"): DELETION_POLICY,
            Optional("retention_policy"): RETENTION_POLICY,
        }
    },
}

_S3_POLICY_DEFINITION = dict(S3_BASE)
_S3_POLICY_DEFINITION.update({"type": "s3-policy"})
S3_POLICY_SCHEMA = Schema(_S3_POLICY_DEFINITION)

_S3_DEFINITION = dict(S3_BASE)
_S3_DEFINITION.update(
    {
        "type": "s3",
        Optional("objects"): [
            {
                "key": str,
                Optional("body"): str,
            }
        ],
    }
)
S3_SCHEMA = Schema(_S3_DEFINITION)

AURORA_SCHEMA = Schema(
    {
        "type": "aurora-postgres",
        "version": NUMBER,
        Optional("deletion_policy"): DB_DELETION_POLICY,
        Optional("environments"): {
            ENV_NAME: {
                Optional("min_capacity"): float_between_with_halfstep(0.5, 128),
                Optional("max_capacity"): float_between_with_halfstep(0.5, 128),
                Optional("snapshot_id"): str,
                Optional("deletion_policy"): DB_DELETION_POLICY,
                Optional("deletion_protection"): DELETION_PROTECTION,
            }
        },
        Optional("services"): Or("__all__", [str]),
        Optional("objects"): [
            {
                "key": str,
                Optional("body"): str,
            }
        ],
    }
)

RDS_SCHEMA = Schema(
    {
        "type": "rds-postgres",
        "version": NUMBER,
        Optional("deletion_policy"): DB_DELETION_POLICY,
        Optional("environments"): {
            ENV_NAME: {
                Optional("plan"): RDS_PLANS,
                Optional("volume_size"): int_between(20, 10000),
                Optional("iops"): int_between(1000, 9950),
                Optional("snapshot_id"): str,
                Optional("deletion_policy"): DB_DELETION_POLICY,
                Optional("deletion_protection"): DELETION_PROTECTION,
            }
        },
        Optional("services"): Or("__all__", [str]),
        Optional("objects"): [
            {
                "key": str,
                Optional("body"): str,
            }
        ],
    }
)

REDIS_SCHEMA = Schema(
    {
        "type": "redis",
        Optional("environments"): {
            ENV_NAME: {
                Optional("plan"): REDIS_PLANS,
                Optional("engine"): REDIS_ENGINE_VERSIONS,
                Optional("replicas"): int_between(0, 5),
                Optional("deletion_policy"): DELETION_POLICY,
            }
        },
    }
)

OPENSEARCH_MIN_VOLUME_SIZE = 10
OPENSEARCH_MAX_VOLUME_SIZE = {
    "tiny": 100,
    "small": 200,
    "small-ha": 200,
    "medium": 512,
    "medium-ha": 512,
    "large": 1000,
    "large-ha": 1000,
    "x-large": 1500,
    "x-large-ha": 1500,
}


class ConditionalSchema(Schema):
    def validate(self, data, _is_conditional_schema=True):
        data = super(ConditionalSchema, self).validate(data, _is_conditional_schema=False)
        if _is_conditional_schema:
            default_plan = None
            default_volume_size = None
            if data["environments"].get("default", None):
                default_plan = data["environments"]["default"].get("plan", None)
                default_volume_size = data["environments"]["default"].get("volume_size", None)

            for env in data["environments"]:
                volume_size = data["environments"][env].get("volume_size", default_volume_size)
                plan = data["environments"][env].get("plan", default_plan)

                if volume_size:
                    if not plan:
                        raise SchemaError(f"Missing key: 'plan'")

                    if volume_size < OPENSEARCH_MIN_VOLUME_SIZE:
                        raise SchemaError(
                            f"Key 'environments' error: Key '{env}' error: Key 'volume_size' error: should be an integer greater than {OPENSEARCH_MIN_VOLUME_SIZE}"
                        )

                    for key in OPENSEARCH_MAX_VOLUME_SIZE:
                        if plan == key and not volume_size <= OPENSEARCH_MAX_VOLUME_SIZE[key]:
                            raise SchemaError(
                                f"Key 'environments' error: Key '{env}' error: Key 'volume_size' error: should be an integer between {OPENSEARCH_MIN_VOLUME_SIZE} and {OPENSEARCH_MAX_VOLUME_SIZE[key]} for plan {plan}"
                            )

        return data


OPENSEARCH_SCHEMA = ConditionalSchema(
    {
        "type": "opensearch",
        Optional("environments"): {
            ENV_NAME: {
                Optional("engine"): OPENSEARCH_ENGINE_VERSIONS,
                Optional("deletion_policy"): DELETION_POLICY,
                Optional("plan"): OPENSEARCH_PLANS,
                Optional("volume_size"): int,
            }
        },
    }
)

MONITORING_SCHEMA = Schema(
    {
        "type": "monitoring",
        Optional("environments"): {
            ENV_NAME: {
                Optional("enable_ops_center"): bool,
            }
        },
    }
)


def no_param_schema(schema_type):
    return Schema({"type": schema_type, Optional("services"): Or("__all__", [str])})


SCHEMA_MAP = {
    "s3": S3_SCHEMA,
    "s3-policy": S3_POLICY_SCHEMA,
    "aurora-postgres": AURORA_SCHEMA,
    "rds-postgres": RDS_SCHEMA,
    "redis": REDIS_SCHEMA,
    "opensearch": OPENSEARCH_SCHEMA,
    "monitoring": MONITORING_SCHEMA,
    "appconfig-ipfilter": no_param_schema("appconfig-ipfilter"),
    "subscription-filter": no_param_schema("subscription-filter"),
    "vpc": no_param_schema("vpc"),
    "xray": no_param_schema("xray"),
}
