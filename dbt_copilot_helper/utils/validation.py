import re

from schema import Optional
from schema import Or
from schema import Regex
from schema import Schema
from schema import SchemaError


def validate_string(regex_pattern):
    def validator(string):
        if not re.match(regex_pattern, string):
            raise SchemaError(
                f"String '{string}' does not match the required pattern '{regex_pattern}'. For more details on valid string patterns see: https://aws.github.io/copilot-cli/docs/manifest/lb-web-service/"
            )
        return string

    return validator


def validate_s3_bucket_name(name):
    return False


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
                errors[
                    addon_name
                ] = f"Unsupported addon type '{addon_type}' in addon '{addon_name}'"
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
    error="Environment name {} is invalid: names must only contain alphanumeric characters."
    # It would be nice if this worked, but it doesn't seem to for dictionary keys.
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
                Optional("backing-services"): [
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
                        Optional("paas-description"): str,
                        Optional("paas-instance"): str,
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
    "tiny", "small", "small-ha", "medium", "medium-ha", "large", "large-ha", "xlarge", "xlarge-ha"
)
RDS_INSTANCE_TYPES = Or(
    "db.m5.2xlarge", "db.m5.4xlarge", "db.m5.large", "db.t3.micro", "db.t3.small"
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

REDIS_ENGINE_VERSIONS = Or("3.2.6", "4.0.10", "5.0.0", "5.0.3", "5.0.4", "5.0.6", "6.0", "6.2")

REDIS_INSTANCE_TYPES = Or(
    "cache.m6g.2xlarge",
    "cache.m6g.large",
    "cache.m6g.xlarge",
    "cache.t4g.medium",
    "cache.t4g.micro",
)

OPENSEARCH_PLANS = Or(
    "tiny", "small", "small-ha", "medium", "medium-ha", "large", "large-ha", "x-large", "x-large-ha"
)

OPENSEARCH_ENGINE_VERSIONS = Or("2.5", "2.3", "1.3", "1.2", "1.1", "1.0")

OPENSEARCH_INSTANCE_TYPES = Or(
    "m6g.2xlarge.search",
    "m6g.large.search",
    "m6g.xlarge.search",
    "t2.medium.search",
    "t3.medium.search",
)

S3_BASE = {
    Optional("readonly"): bool,
    Optional("deletion-policy"): DELETION_POLICY,
    Optional("services"): Or("__all__", [str]),
    Optional("environments"): {
        ENV_NAME: {
            "bucket-name": Regex(r"^(?!(^xn--|.+-s3alias$))^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$"),
            Optional("deletion-policy"): DELETION_POLICY,
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
        Optional("deletion-policy"): DB_DELETION_POLICY,
        Optional("environments"): {
            ENV_NAME: {
                Optional("min-capacity"): float_between_with_halfstep(0.5, 128),
                Optional("max-capacity"): float_between_with_halfstep(0.5, 128),
                Optional("snapshot-id"): str,
                Optional("deletion-policy"): DB_DELETION_POLICY,
                Optional("deletion-protection"): DELETION_PROTECTION,
            }
        },
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
        Optional("deletion-policy"): DB_DELETION_POLICY,
        Optional("environments"): {
            ENV_NAME: {
                Optional("plan"): RDS_PLANS,
                Optional("instance"): RDS_INSTANCE_TYPES,
                Optional("volume-size"): int_between(5, 10000),
                Optional("replicas"): int_between(0, 5),
                Optional("snapshot-id"): str,
                Optional("deletion-policy"): DB_DELETION_POLICY,
                Optional("deletion-protection"): DELETION_PROTECTION,
            }
        },
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
        Optional("deletion-policy"): DELETION_POLICY,
        Optional("environments"): {
            ENV_NAME: {
                Optional("plan"): REDIS_PLANS,
                Optional("engine"): REDIS_ENGINE_VERSIONS,
                Optional("replicas"): int_between(0, 5),
                Optional("instance"): REDIS_INSTANCE_TYPES,
                Optional("deletion-policy"): DELETION_POLICY,
            }
        },
    }
)

OPENSEARCH_SCHEMA = Schema(
    {
        "type": "opensearch",
        Optional("deletion-policy"): DELETION_POLICY,
        Optional("environments"): {
            ENV_NAME: {
                Optional("plan"): OPENSEARCH_PLANS,
                Optional("engine"): OPENSEARCH_ENGINE_VERSIONS,
                Optional("replicas"): int_between(0, 5),
                Optional("instance"): OPENSEARCH_INSTANCE_TYPES,
                Optional("volume_size"): int_between(10, 511),
                Optional("deletion-policy"): DELETION_POLICY,
            }
        },
    }
)

MONITORING_SCHEMA = Schema(
    {
        "type": "monitoring",
        Optional("environments"): {
            ENV_NAME: {
                Optional("enable-ops-center"): bool,
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
