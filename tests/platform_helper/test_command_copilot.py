import os
import re
from pathlib import Path
from pathlib import PosixPath
from unittest.mock import Mock
from unittest.mock import patch

import boto3
import pytest
import yaml
from botocore.exceptions import ClientError
from click.testing import CliRunner
from freezegun import freeze_time
from moto import mock_iam
from moto import mock_s3
from moto import mock_ssm
from moto import mock_sts
from yaml import dump

from dbt_platform_helper.commands.copilot import copilot
from dbt_platform_helper.commands.copilot import is_service
from dbt_platform_helper.utils.aws import SSM_PATH
from dbt_platform_helper.utils.validation import BUCKET_NAME_IN_USE_TEMPLATE
from tests.platform_helper.conftest import FIXTURES_DIR
from tests.platform_helper.conftest import mock_aws_client

REDIS_STORAGE_CONTENTS = """
redis:
  type: redis
  environments:
    default:
      engine: '6.2'
      plan: small
"""

RDS_POSTGRES_STORAGE_CONTENTS = """
rds:
  type: rds-postgres
  version: 14.4
  environments:
    default:
      plan: small-ha
"""

AURORA_POSTGRES_STORAGE_CONTENTS = """
aurora:
  type: aurora-postgres
  version: 14.4
  environments:
    default:
      min_capacity: 0.5
      max_capacity: 8
"""

OPENSEARCH_STORAGE_CONTENTS = """
opensearch:
  type: opensearch
  environments:
    default:
      plan: small
      engine: "2.3"
"""

S3_STORAGE_CONTENTS = """
s3:
  type: s3
  readonly: true
  services:
    - "web"
  environments:
    development:
      bucket_name: my-bucket-dev
"""

WEB_SERVICE_CONTENTS = """
name: web
type: Load Balanced Web Service
"""

ADDON_CONFIG_FILENAME = "addons.yml"


class TestMakeAddonCommand:
    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=True),
    )
    def test_validate_version_called_once(self, validate_version):
        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 1
        validate_version.assert_called_once()

    @pytest.mark.parametrize(
        "addon_file, expected_env_addons, expected_service_addons, expect_db_warning",
        [
            (
                "s3_addons.yml",
                [
                    "my-s3-bucket.yml",
                    "my-s3-bucket-with-an-object.yml",
                    "addons.parameters.yml",
                    "monitoring.yml",
                    "vpc.yml",
                ],
                [
                    "appconfig-ipfilter.yml",
                    "subscription-filter.yml",
                    "my-s3-bucket.yml",
                    "my-s3-bucket-with-an-object.yml",
                    "my-s3-bucket-bucket-access.yml",
                ],
                False,
            ),
            (
                "opensearch_addons.yml",
                [
                    "my-opensearch.yml",
                    "my-opensearch-longer.yml",
                    "addons.parameters.yml",
                    "monitoring.yml",
                    "vpc.yml",
                ],
                ["appconfig-ipfilter.yml", "subscription-filter.yml"],
                False,
            ),
            (
                "rds_addons.yml",
                ["my-rds-db.yml", "addons.parameters.yml", "monitoring.yml", "vpc.yml"],
                [
                    "appconfig-ipfilter.yml",
                    "subscription-filter.yml",
                    "my-rds-db.yml",
                ],
                True,
            ),
            (
                "redis_addons.yml",
                ["my-redis.yml", "addons.parameters.yml", "monitoring.yml", "vpc.yml"],
                ["appconfig-ipfilter.yml", "subscription-filter.yml"],
                False,
            ),
            (
                "aurora_addons.yml",
                ["my-aurora-db.yml", "addons.parameters.yml", "monitoring.yml", "vpc.yml"],
                [
                    "appconfig-ipfilter.yml",
                    "subscription-filter.yml",
                    "my-aurora-db.yml",
                ],
                True,
            ),
            (
                "monitoring_addons.yml",
                ["monitoring.yml", "addons.parameters.yml", "vpc.yml"],
                ["appconfig-ipfilter.yml", "subscription-filter.yml"],
                False,
            ),
        ],
    )
    @freeze_time("2023-08-22 16:00:00")
    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @patch("dbt_platform_helper.jinja2_tags.version", new=Mock(return_value="v0.1-TEST"))
    @patch(
        "dbt_platform_helper.commands.copilot.get_log_destination_arn",
        new=Mock(
            return_value='{"prod": "arn:cwl_log_destination_prod", "dev": "arn:dev_cwl_log_destination"}'
        ),
    )
    @mock_s3
    @mock_sts
    @mock_iam
    def test_make_addons_success(
        self,
        fakefs,
        addon_file,
        expected_env_addons,
        expected_service_addons,
        expect_db_warning,
    ):
        """Test that make_addons generates the expected directories and file
        contents."""
        # Arrange
        addons_dir = FIXTURES_DIR / "make_addons"
        fakefs.add_real_directory(
            addons_dir / "config/copilot", read_only=False, target_path="copilot"
        )
        fakefs.add_real_file(
            addons_dir / addon_file, read_only=False, target_path=ADDON_CONFIG_FILENAME
        )
        fakefs.add_real_directory(Path(addons_dir, "expected"), target_path="expected")

        # Act
        result = CliRunner().invoke(copilot, ["make-addons"])

        assert (
            result.exit_code == 0
        ), f"The exit code should have been 0 (success) but was {result.exit_code}"
        db_warning = "Note: The key DATABASE_CREDENTIALS may need to be changed"
        assert (
            db_warning in result.stdout
        ) == expect_db_warning, "If we have a DB addon we expect a warning"

        expected_env_files = [
            Path("environments/addons", filename) for filename in expected_env_addons
        ]
        expected_service_files = [
            Path("web/addons", filename) for filename in expected_service_addons
        ]
        all_expected_files = expected_env_files + expected_service_files

        for f in all_expected_files:
            expected_file = Path("expected", f)

            if f.name == "vpc.yml":
                if addon_file == "rds_addons.yml":
                    vpc_file = "rds-postgres"
                elif addon_file == "aurora_addons.yml":
                    vpc_file = "aurora-postgres"
                else:
                    vpc_file = "default"

                expected_file = Path(
                    "expected/environments/addons",
                    f"vpc-{vpc_file}.yml",
                )

            if f.name == "addons.parameters.yml" and addon_file in [
                "rds_addons.yml",
                "aurora_addons.yml",
            ]:
                expected_file = Path(
                    "expected/environments/addons",
                    "addons.parameters.rds.yml",
                )

            expected = yaml.safe_load(expected_file.read_text())
            actual = yaml.safe_load(Path("copilot", f).read_text())

            assert sorted(expected) == sorted(
                actual
            ), f"The file {f} did not have the expected content"

            assert actual == expected

        env_override_files = setup_override_files_for_environments()
        for file in env_override_files:
            assert f"{file} created" in result.stdout
        all_expected_files += env_override_files

        expected_svc_overrides_file = Path("expected/web/overrides/cfn.patches.yml").read_text()
        actual_svc_overrides_file = Path("copilot/web/overrides/cfn.patches.yml").read_text()
        assert actual_svc_overrides_file == expected_svc_overrides_file

        copilot_dir = Path("copilot")
        actual_files = [
            Path(d, f).relative_to(copilot_dir)
            for d, _, files in os.walk(copilot_dir)
            for f in files
        ]

        assert (
            len(actual_files) == len(all_expected_files) + 4
        ), "The actual filecount should be expected files plus 3 initial manifest.yml and 1 override files"

    @freeze_time("2023-08-22 16:00:00")
    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @patch("dbt_platform_helper.jinja2_tags.version", new=Mock(return_value="v0.1-TEST"))
    @patch(
        "dbt_platform_helper.commands.copilot.get_log_destination_arn",
        new=Mock(
            return_value='{"prod": "arn:cwl_log_destination_prod", "dev": "arn:dev_cwl_log_destination"}'
        ),
    )
    @patch("dbt_platform_helper.utils.validation.get_aws_session_or_abort")
    def test_make_addons_success_but_warns_when_bucket_name_in_use(self, mock_get_session, fakefs):
        client = mock_aws_client(mock_get_session)
        client.head_bucket.side_effect = ClientError({"Error": {"Code": "400"}}, "HeadBucket")
        """Test that make_addons generates the expected directories and file
        contents."""
        # Arrange
        addons_dir = FIXTURES_DIR / "make_addons"
        fakefs.add_real_directory(
            addons_dir / "config/copilot", read_only=False, target_path="copilot"
        )
        fakefs.add_real_file(
            addons_dir / "s3_addons.yml", read_only=False, target_path=ADDON_CONFIG_FILENAME
        )
        fakefs.add_real_directory(Path(addons_dir, "expected"), target_path="expected")

        # Act
        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 0
        assert BUCKET_NAME_IN_USE_TEMPLATE.format("my-bucket") in result.output

    @freeze_time("2023-08-22 16:00:00")
    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @patch("dbt_platform_helper.jinja2_tags.version", new=Mock(return_value="v0.1-TEST"))
    @patch(
        "dbt_platform_helper.commands.copilot.get_log_destination_arn",
        new=Mock(
            return_value='{"prod": "arn:cwl_log_destination_prod", "dev": "arn:dev_cwl_log_destination"}'
        ),
    )
    def test_make_addons_removes_old_addons_files(
        self,
        fakefs,
    ):
        """Tests that old addons files are cleaned up before generating new
        ones."""
        # Arrange
        addons_dir = FIXTURES_DIR / "make_addons"
        fakefs.add_real_directory(
            addons_dir / "config/copilot", read_only=False, target_path="copilot"
        )
        fakefs.add_real_file(
            addons_dir / "redis_addons.yml",
            read_only=False,
            target_path=ADDON_CONFIG_FILENAME,
        )
        fakefs.add_real_directory(Path(addons_dir, "expected"), target_path="expected")

        # Add some legacy addon files:
        old_addon_files = [
            "environments/addons/my-s3-bucket.yml",
            "environments/addons/my-s3-bucket-with-an-object.yml",
            "environments/addons/my-opensearch.yml",
            "environments/addons/my-rds-db.yml",
            "web/addons/my-s3-bucket.yml",
            "web/addons/my-s3-bucket-with-an-object.yml",
            "web/addons/my-s3-bucket-bucket-access.yml",
        ]

        for f in old_addon_files:
            fakefs.add_real_file(
                addons_dir / "expected" / f,
                read_only=False,
                target_path=Path("copilot", f),
            )

        # Act
        CliRunner().invoke(copilot, ["make-addons"])

        # Assert
        expected_env_files = [
            Path("environments/addons", f)
            for f in ["my-redis.yml", "addons.parameters.yml", "vpc.yml"]
        ]
        expected_service_files = [
            Path("web/addons", f) for f in ["appconfig-ipfilter.yml", "subscription-filter.yml"]
        ]
        all_expected_files = expected_env_files + expected_service_files

        for f in all_expected_files:
            expected_file = Path(
                "expected",
                f if not f.name == "vpc.yml" else "environments/addons/vpc-default.yml",
            )
            expected = yaml.safe_load(expected_file.read_text())
            actual = yaml.safe_load(Path("copilot", f).read_text())
            assert sorted(actual) == sorted(
                expected
            ), f"The file {f} did not have the expected content"

        for f in old_addon_files:
            path = Path("copilot", f)
            assert not path.exists()

    @pytest.mark.parametrize(
        "addon_file, addon_name",
        [
            (S3_STORAGE_CONTENTS, "s3"),
            (REDIS_STORAGE_CONTENTS, "redis"),
            (RDS_POSTGRES_STORAGE_CONTENTS, "rds"),
            (AURORA_POSTGRES_STORAGE_CONTENTS, "aurora"),
            (OPENSEARCH_STORAGE_CONTENTS, "opensearch"),
        ],
    )
    @pytest.mark.parametrize(
        "deletion_policy_override, expected_deletion_policy",
        [
            (None, "Delete"),
            ("Retain", "Retain"),
            ("Delete", "Delete"),
        ],
    )
    @freeze_time("2023-08-22 16:00:00")
    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @patch("dbt_platform_helper.jinja2_tags.version", new=Mock(return_value="v0.1-TEST"))
    @patch(
        "dbt_platform_helper.commands.copilot.get_log_destination_arn",
        new=Mock(
            return_value='{"prod": "arn:cwl_log_destination_prod", "dev": "arn:dev_cwl_log_destination"}'
        ),
    )
    @mock_s3
    @mock_sts
    @mock_iam
    def test_make_addons_deletion_policy(
        self,
        fakefs,
        addon_file,
        addon_name,
        deletion_policy_override,
        expected_deletion_policy,
    ):
        """Test that deletion policy defaults and overrides are applied
        correctly."""
        addon_file_contents = yaml.safe_load(addon_file)
        if deletion_policy_override:
            for env in addon_file_contents[addon_name]["environments"]:
                addon_file_contents[addon_name]["environments"][env][
                    "deletion_policy"
                ] = deletion_policy_override

        create_test_manifests([dump(addon_file_contents)], fakefs)

        CliRunner().invoke(copilot, ["make-addons"])

        manifest = yaml.safe_load(
            Path(f"/copilot/environments/addons/{addon_name}.yml").read_text()
        )
        assert (
            manifest["Mappings"][f"{addon_name}EnvironmentConfigMap"]["development"][
                "DeletionPolicy"
            ]
            == expected_deletion_policy
        )

    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    def test_exit_if_no_copilot_directory(self, fakefs):
        fakefs.create_file(ADDON_CONFIG_FILENAME)

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 1
        assert (
            result.output
            == "DeprecationWarning: The command 'make-addons' is deprecated.\nCannot find copilot directory. Run this command in the root of the deployment "
            "repository.\n"
        )

    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    def test_exit_if_no_local_copilot_services(self, fakefs):
        fakefs.create_file(ADDON_CONFIG_FILENAME)

        fakefs.create_file("copilot/environments/development/manifest.yml")

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 1
        assert (
            result.output
            == "DeprecationWarning: The command 'make-addons' is deprecated.\nNo services found in ./copilot/; exiting\n"
        )

    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @mock_s3
    @mock_sts
    @mock_iam
    def test_exit_with_error_if_invalid_services(self, fakefs):
        fakefs.create_file(
            ADDON_CONFIG_FILENAME,
            contents="""
invalid-entry:
    type: s3-policy
    services:
        - does-not-exist
        - also-does-not-exist
    environments:
        default:
            bucket_name: test-bucket
""",
        )

        fakefs.create_file("copilot/environments/development/manifest.yml")

        fakefs.create_file(
            "copilot/web/manifest.yml",
            contents=" ".join([yaml.dump(yaml.safe_load(WEB_SERVICE_CONTENTS))]),
        )

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 1
        assert (
            "Services listed in invalid-entry.services do not exist in ./copilot/" in result.output
        )

    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @mock_s3
    @mock_sts
    @mock_iam
    def test_exit_with_error_if_addons_yml_validation_fails(self, fakefs):
        fakefs.create_file(
            ADDON_CONFIG_FILENAME,
            contents="""
example-invalid-file:
    type: s3
    environments:
        default:
            bucket_name: test-bucket
            no_such_key: bad-key
""",
        )

        fakefs.create_file("copilot/environments/development/manifest.yml")
        fakefs.create_file(
            "copilot/web/manifest.yml",
            contents=" ".join([yaml.dump(yaml.safe_load(WEB_SERVICE_CONTENTS))]),
        )

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 1
        assert re.match(
            r"(?s).*example-invalid-file.*environments.*default.*Wrong key 'no_such_key'",
            result.output,
        )

    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @mock_s3
    @mock_sts
    @mock_iam
    def test_exit_with_error_if_invalid_environments(self, fakefs):
        fakefs.create_file(
            ADDON_CONFIG_FILENAME,
            contents="""
invalid-environment:
    type: s3-policy
    environments:
        doesnotexist:
            bucket_name: test-bucket
""",
        )

        fakefs.create_file("copilot/environments/development/manifest.yml")

        fakefs.create_file(
            "copilot/web/manifest.yml",
            contents=" ".join([yaml.dump(yaml.safe_load(WEB_SERVICE_CONTENTS))]),
        )

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 1
        assert (
            "Environment keys listed in invalid-environment do not match ./copilot/environments"
            in result.output
        )

    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @mock_s3
    @mock_sts
    @mock_iam
    def test_exit_with_multiple_errors(self, fakefs):
        fakefs.create_file(
            ADDON_CONFIG_FILENAME,
            contents="""
my-s3-bucket-1:
  type: s3
  environments:
    dev:
      bucket_name: sthree-one..TWO-s3alias # Many naming errors

my-s3-bucket-2:
  type: s3
  environments:
    dev:
      bucket_name: charles
      deletion_policy: ThisIsInvalid # Should be a valid policy name.
""",
        )

        fakefs.create_file("copilot/environments/development/manifest.yml")

        fakefs.create_file(
            "copilot/web/manifest.yml",
            contents=" ".join([yaml.dump(yaml.safe_load(WEB_SERVICE_CONTENTS))]),
        )

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 1
        assert "Errors found in addons.yml:" in result.output
        assert "'Delete' does not match 'ThisIsInvalid'" in result.output
        assert "Names cannot be prefixed 'sthree-'" in result.output
        assert "Names cannot be suffixed '-s3alias'" in result.output
        assert "Names cannot contain two adjacent periods" in result.output
        assert "Names can only contain the characters 0-9, a-z, '.' and '-'." in result.output

    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    def test_exit_if_services_key_invalid(self, fakefs):
        """
        The services key can be set to a list of services, or '__all__' which
        denotes that it should be applied to all services.

        Any other string value results in an error.
        """

        fakefs.create_file(
            ADDON_CONFIG_FILENAME,
            contents="""
invalid-entry:
    type: s3-policy
    services: this-is-not-valid
    environments:
        default:
            bucket-name: test-bucket
""",
        )

        fakefs.create_file("copilot/environments/development/manifest.yml")

        fakefs.create_file(
            "copilot/web/manifest.yml",
            contents=" ".join([yaml.dump(yaml.safe_load(WEB_SERVICE_CONTENTS))]),
        )

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 1
        assert "Key 'services' error:" in result.output
        assert "'__all__' does not match 'this-is-not-valid'" in result.output
        assert "'this-is-not-valid' should be instance of 'list'" in result.output

    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    def test_exit_if_no_local_copilot_environments(self, fakefs):
        fakefs.create_file(ADDON_CONFIG_FILENAME)

        fakefs.create_file(
            "copilot/web/manifest.yml",
            contents=" ".join([yaml.dump(yaml.safe_load(WEB_SERVICE_CONTENTS))]),
        )

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 1
        assert (
            result.output
            == "DeprecationWarning: The command 'make-addons' is deprecated.\nNo environments found in ./copilot/environments; exiting\n"
        )

    @pytest.mark.parametrize(
        "addon_file_contents, has_postgres_addon",
        [
            ([REDIS_STORAGE_CONTENTS], False),
            ([RDS_POSTGRES_STORAGE_CONTENTS], True),
            ([AURORA_POSTGRES_STORAGE_CONTENTS], True),
            ([OPENSEARCH_STORAGE_CONTENTS], False),
            # Check when we have a mix of addons...
            (
                [
                    RDS_POSTGRES_STORAGE_CONTENTS,
                    OPENSEARCH_STORAGE_CONTENTS,
                    S3_STORAGE_CONTENTS,
                ],
                True,
            ),
        ],
    )
    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @patch("dbt_platform_helper.jinja2_tags.version", new=Mock(return_value="v0.1-TEST"))
    @patch(
        "dbt_platform_helper.commands.copilot.get_log_destination_arn",
        new=Mock(
            return_value='{"prod": "arn:cwl_log_destination_prod", "dev": "arn:dev_cwl_log_destination"}'
        ),
    )
    @mock_s3
    @mock_sts
    @mock_iam
    def test_addons_parameters_file_included_with_required_parameters_for_the_addon_types(
        self, fakefs, addon_file_contents, has_postgres_addon
    ):
        def assert_in_addons_parameters_as_required(
            checks, addons_parameters_contents, should_include
        ):
            should_or_should_not_string = "should"
            if not should_include:
                should_or_should_not_string += " not"
            for check in checks:
                assert (
                    check in addons_parameters_contents
                ) == should_include, (
                    f"'{check}' {should_or_should_not_string} be included in addons.parameters.yml"
                )

        create_test_manifests(addon_file_contents, fakefs)

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 0
        assert (
            "File copilot/environments/addons/addons.parameters.yml created" in result.output
        ), "addons.parameters.yml should be included"
        addons_parameters_contents = Path(
            "/copilot/environments/addons/addons.parameters.yml"
        ).read_text()
        assert_in_addons_parameters_as_required(
            checks=[
                "EnvironmentSecurityGroup: !Ref EnvironmentSecurityGroup",
                "PrivateSubnets: !Join [ ',', [ !Ref PrivateSubnet1, !Ref PrivateSubnet2, ] ]",
                "PublicSubnets: !Join [ ',', [ !Ref PublicSubnet1, !Ref PublicSubnet2, ] ]",
                "VpcId: !Ref VPC",
            ],
            addons_parameters_contents=addons_parameters_contents,
            should_include=True,
        )
        assert_in_addons_parameters_as_required(
            checks=[
                "DefaultPublicRoute: !Ref DefaultPublicRoute",
                "InternetGateway: !Ref InternetGateway",
                "InternetGatewayAttachment: !Ref InternetGatewayAttachment",
                "PublicRouteTable: !Ref PublicRouteTable",
                "PublicSubnet1RouteTableAssociation: !Ref PublicSubnet1RouteTableAssociation",
                "PublicSubnet2RouteTableAssociation: !Ref PublicSubnet2RouteTableAssociation",
            ],
            addons_parameters_contents=addons_parameters_contents,
            should_include=has_postgres_addon,
        )

    @pytest.mark.parametrize(
        "addon_file_contents, addon_type, secret_name",
        [
            ([REDIS_STORAGE_CONTENTS], "redis", "REDIS"),
            ([RDS_POSTGRES_STORAGE_CONTENTS], "rds-postgres", "RDS"),
            ([AURORA_POSTGRES_STORAGE_CONTENTS], "aurora-postgres", "AURORA"),
        ],
    )
    @patch("dbt_platform_helper.jinja2_tags.version", new=Mock(return_value="v0.1-TEST"))
    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @patch(
        "dbt_platform_helper.commands.copilot.get_log_destination_arn",
        new=Mock(
            return_value='{"prod": "arn:cwl_log_destination_prod", "dev": "arn:dev_cwl_log_destination"}'
        ),
    )
    def test_addon_instructions_with_postgres_addon_types(
        self, fakefs, addon_file_contents, addon_type, secret_name
    ):
        create_test_manifests(addon_file_contents, fakefs)

        result = CliRunner().invoke(copilot, ["make-addons"])

        assert result.exit_code == 0
        if addon_type == "redis":
            assert (
                "DATABASE_CREDENTIALS" not in result.output
            ), f"DATABASE_CREDENTIALS should not be included for {addon_type}"
        else:
            assert (
                "DATABASE_CREDENTIALS" in result.output
            ), f"DATABASE_CREDENTIALS should be included for {addon_type}"
            assert (
                "secretsmanager: /copilot/${COPILOT_APPLICATION_NAME}/${COPILOT_ENVIRONMENT_NAME}/secrets/"
                f"{secret_name}" in result.output
            )

    @patch(
        "dbt_platform_helper.utils.versioning.running_as_installed_package",
        new=Mock(return_value=False),
    )
    @patch("dbt_platform_helper.jinja2_tags.version", new=Mock(return_value="v0.1-TEST"))
    @patch(
        "dbt_platform_helper.commands.copilot.get_log_destination_arn",
        new=Mock(
            return_value='{"prod": "arn:cwl_log_destination_prod", "dev": "arn:dev_cwl_log_destination"}'
        ),
    )
    def test_appconfig_ip_filter_policy_is_applied_to_each_service_by_default(self, fakefs):
        services = ["web", "web-celery"]

        fakefs.create_file(ADDON_CONFIG_FILENAME)

        fakefs.create_file(
            "./copilot/environments/development/manifest.yml",
        )

        for service in services:
            fakefs.create_file(
                f"copilot/{service}/manifest.yml",
                contents=" ".join([yaml.dump(yaml.safe_load(WEB_SERVICE_CONTENTS))]),
            )

        result = CliRunner().invoke(copilot, ["make-addons"])

        for service in services:
            for custom_addon in ["appconfig-ipfilter.yml", "subscription-filter.yml"]:
                path = Path(f"copilot/{service}/addons/{custom_addon}")
                assert path.exists()

        assert result.exit_code == 0


@mock_ssm
@mock_sts
@mock_iam
@patch(
    "dbt_platform_helper.utils.versioning.running_as_installed_package",
    new=Mock(return_value=False),
)
def test_get_secrets():
    def _put_ssm_param(client, app, env, name, value):
        path = SSM_PATH.format(app=app, env=env, name=name)
        client.put_parameter(Name=path, Value=value, Type="String")

    ssm = boto3.client("ssm")

    secrets = [
        ["MY_SECRET", "testing"],
        ["MY_SECRET2", "hello"],
        ["MY_SECRET3", "world"],
    ]

    for name, value in secrets:
        _put_ssm_param(ssm, "myapp", "myenv", name, value)

    _put_ssm_param(ssm, "myapp", "anotherenv", "OTHER_ENV", "foobar")

    result = CliRunner().invoke(copilot, ["get-env-secrets", "myapp", "myenv"])

    for name, value in secrets:
        path = SSM_PATH.format(app="myapp", env="myenv", name=name)
        line = f"{path}: {value}"

        assert line in result.output

    assert SSM_PATH.format(app="myapp", env="anotherenv", name="OTHER_ENV") not in result.output
    assert result.exit_code == 0


def create_test_manifests(addon_file_contents, fakefs):
    fakefs.create_file(
        ADDON_CONFIG_FILENAME,
        contents=" ".join(addon_file_contents),
    )
    fakefs.create_file(
        "copilot/web/manifest.yml",
        contents=" ".join([yaml.dump(yaml.safe_load(WEB_SERVICE_CONTENTS))]),
    )
    fakefs.create_file("copilot/environments/development/manifest.yml")


@pytest.mark.parametrize(
    "service_type, expected",
    [
        ("Load Balanced Web Service", True),
        ("Backend Service", True),
        ("Request-Driven Web Service", True),
        ("Static Site", True),
        ("Worker Service", True),
        ("Scheduled Job", False),
    ],
)
def test_is_service(fakefs, service_type, expected):
    manifest_contents = f"""
    type: {service_type}
    """
    fakefs.create_file(
        "copilot/web/manifest.yml",
        contents=" ".join([yaml.dump(yaml.safe_load(manifest_contents))]),
    )

    assert is_service(PosixPath("copilot/web/manifest.yml")) == expected


def test_is_service_empty_manifest(fakefs, capfd):
    file_path = "copilot/web/manifest.yml"
    fakefs.create_file(file_path)

    with pytest.raises(SystemExit) as excinfo:
        is_service(PosixPath(file_path))

    assert excinfo.value.code == 1
    assert f"No type defined in manifest file {file_path}; exiting" in capfd.readouterr().out


def setup_override_files_for_environments():
    overrides_dir = Path("./copilot/environments/overrides")
    return (
        overrides_dir / "bin" / "override.ts",
        overrides_dir / ".gitignore",
        overrides_dir / "cdk.json",
        overrides_dir / "log_resource_policy.json",
        overrides_dir / "package-lock.json",
        overrides_dir / "package.json",
        overrides_dir / "README.md",
        overrides_dir / "stack.ts",
        overrides_dir / "tsconfig.json",
    )
