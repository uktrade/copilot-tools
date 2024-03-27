import os
from pathlib import Path
from shutil import copyfile
from shutil import rmtree

import pytest
from click.testing import CliRunner

from dbt_platform_helper.commands.bootstrap import make_config
from dbt_platform_helper.commands.check_cloudformation import (
    check_cloudformation as check_cloudformation_command,
)
from dbt_platform_helper.commands.copilot import make_addons
from tests.platform_helper.conftest import FIXTURES_DIR
from tests.platform_helper.conftest import TEST_APP_DIR


def prepare_fake_cloudformation_templates(template: str) -> None:
    addons_directory = Path(f"{TEST_APP_DIR}/copilot/environments/addons")
    addons_directory.mkdir(parents=True, exist_ok=True)
    copyfile(f"{FIXTURES_DIR}/{template}", f"{addons_directory}/{template}")


def ensure_directory_does_not_exist(copilot_directory: Path) -> None:
    if copilot_directory.exists():
        rmtree(copilot_directory)
    assert not copilot_directory.exists(), "copilot directory should not exist"


@pytest.fixture
def app_with_valid_cf_template(application_under_test):
    prepare_fake_cloudformation_templates("valid_cloudformation_template.yml")


@pytest.fixture
def app_with_invalid_cf_template(application_under_test):
    prepare_fake_cloudformation_templates("invalid_cloudformation_template.yml")


@pytest.fixture
def app_with_insecure_cf_template(application_under_test):
    prepare_fake_cloudformation_templates("insecure_cloudformation_template.yml")


@pytest.fixture
def copilot_directory() -> Path:
    return TEST_APP_DIR / "copilot"


@pytest.fixture
def application_under_test(copilot_directory):
    ensure_directory_does_not_exist(copilot_directory)
    os.chdir(copilot_directory.parent)
    CliRunner().invoke(make_config)
    CliRunner().invoke(make_addons)
    yield
    ensure_directory_does_not_exist(copilot_directory)


@pytest.mark.xdist_group(name="fileaccess")
def test_check_cloudformation_with_no_args_summarises_all_successes(
    app_with_valid_cf_template, copilot_directory: Path
) -> None:
    result = CliRunner().invoke(
        check_cloudformation_command, args=["--directory", copilot_directory]
    )

    assert ">>> Running all checks" in result.output
    assert ">>> Running lint check" in result.output
    assert ">>> Running security check" in result.output
    assert (
        "The CloudFormation templates passed the following checks:\n  - lint\n  - check-security"
        in result.output
    )


@pytest.mark.xdist_group(name="fileaccess")
def test_check_cloudformation_with_no_args_summarises_all_failures(
    app_with_invalid_cf_template, copilot_directory: Path
) -> None:
    result = CliRunner().invoke(
        check_cloudformation_command, args=["--directory", copilot_directory]
    )

    assert (
        "The CloudFormation templates failed the following checks:\n  - lint [E0000 could not find expected ':'"
        in result.output
    )


@pytest.mark.xdist_group(name="fileaccess")
@pytest.mark.parametrize("check_type", ["lint", "check-security"])
def test_check_passed(app_with_valid_cf_template, copilot_directory: Path, check_type) -> None:
    result = CliRunner().invoke(
        check_cloudformation_command, args=[check_type, "--directory", copilot_directory]
    )

    assert result.exit_code == 0
    assert (
        f"The CloudFormation templates passed the following checks:\n  - {check_type}"
        in result.output
    )


@pytest.mark.xdist_group(name="fileaccess")
def test_linting_check_failed(app_with_invalid_cf_template, copilot_directory: Path) -> None:
    result = CliRunner().invoke(
        check_cloudformation_command, args=["lint", "--directory", copilot_directory]
    )

    assert result.exit_code != 0
    assert (
        "The CloudFormation templates failed the following checks:\n  - lint [E0000 could not find expected ':'"
        in result.output
    )


@pytest.mark.xdist_group(name="fileaccess")
def test_security_check_failed(app_with_insecure_cf_template, copilot_directory: Path) -> None:
    result = CliRunner().invoke(
        check_cloudformation_command, args=["check-security", "--directory", copilot_directory]
    )

    assert result.exit_code != 0
    assert (
        "The CloudFormation templates failed the following checks:\n  - check-security"
        in result.output
    )
    assert "Ensure RDS database has IAM authentication enabled" in result.output


@pytest.mark.xdist_group(name="fileaccess")
def test_linting_check_multiple_rules_ignored(app_with_valid_cf_template, copilot_directory: Path):
    result = CliRunner().invoke(
        check_cloudformation_command,
        args=[
            "lint",
            "--directory",
            copilot_directory,
            "--ignore-checks",
            "A123",
            "--ignore-checks",
            "B234",
        ],
    )

    assert result.exit_code == 0
    assert "--ignore-checks A123 --ignore-checks B234 --ignore-checks W2001" in result.output
