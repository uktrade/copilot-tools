import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import yaml
from _pytest.fixtures import fixture
from click.testing import CliRunner
from freezegun.api import freeze_time

from dbt_copilot_helper.commands.pipeline import generate_config
from tests.conftest import EXPECTED_FILES_DIR
from tests.conftest import FIXTURES_DIR
from tests.conftest import assert_file_created_in_stdout
from tests.conftest import mock_codestar_connections_boto_client


@freeze_time("2023-08-22 16:00:00")
@patch("dbt_copilot_helper.jinja2_tags.version", new=Mock(return_value="v0.1-TEST"))
@patch("boto3.client")
def test_pipeline_generate_with_git_repo_creates_the_pipeline_configuration(
    mocked_boto3_client, tmp_path, switch_to_tmp_dir_and_copy_fixtures
):
    mock_codestar_connections_boto_client(mocked_boto3_client, ["test-app"])
    setup_git_repository()
    buildspec, cfn_patch, manifest = setup_output_file_paths(tmp_path)

    result = CliRunner().invoke(generate_config)

    expected_files_dir = (
        Path(EXPECTED_FILES_DIR) / "pipeline" / "pipelines" / "test-app-environments"
    )
    assert_yaml_in_output_file_matches_expected(buildspec, expected_files_dir / "buildspec.yml")
    assert_yaml_in_output_file_matches_expected(manifest, expected_files_dir / "manifest.yml")
    assert_yaml_in_output_file_matches_expected(
        cfn_patch, expected_files_dir / "overrides/cfn.patches.yml"
    )
    assert_file_created_in_stdout(buildspec, result, tmp_path)
    assert_file_created_in_stdout(manifest, result, tmp_path)
    assert_file_created_in_stdout(cfn_patch, result, tmp_path)


@freeze_time("2023-08-22 16:00:00")
@patch("dbt_copilot_helper.jinja2_tags.version", new=Mock(return_value="v0.1-TEST"))
@patch("boto3.client")
def test_pipeline_generate_overwrites_any_existing_config_files(
    mocked_boto3_client, tmp_path, switch_to_tmp_dir_and_copy_fixtures
):
    mock_codestar_connections_boto_client(mocked_boto3_client, ["test-app"])
    setup_git_repository()
    buildspec, cfn_patch, manifest = setup_output_file_paths(tmp_path)
    for path in [buildspec, cfn_patch, manifest]:
        os.makedirs(path.parent, exist_ok=True)
        with open(path, "w") as fh:
            print("Pre-existing file contents", file=fh)

    CliRunner().invoke(generate_config)

    expected_files_dir = (
        Path(EXPECTED_FILES_DIR) / "pipeline" / "pipelines" / "test-app-environments"
    )
    assert_yaml_in_output_file_matches_expected(buildspec, expected_files_dir / "buildspec.yml")
    assert_yaml_in_output_file_matches_expected(manifest, expected_files_dir / "manifest.yml")
    assert_yaml_in_output_file_matches_expected(
        cfn_patch, expected_files_dir / "overrides/cfn.patches.yml"
    )


@patch("boto3.client")
def test_pipeline_generate_with_no_codestar_connection_exits_with_message(
    mocked_boto3_client, switch_to_tmp_dir_and_copy_fixtures
):
    mock_codestar_connections_boto_client(mocked_boto3_client, [])
    setup_git_repository()

    result = CliRunner().invoke(generate_config)

    assert result.exit_code == 1
    assert "Error: There is no CodeStar Connection to use" in result.output


def test_pipeline_generate_with_no_repo_fails_with_message(switch_to_tmp_dir_and_copy_fixtures):
    result = CliRunner().invoke(generate_config)

    assert result.exit_code == 1
    assert "Error: The current directory is not a git repository" in result.output


def test_pipeline_generate_with_no_pipeline_yml_fails_with_message(
    switch_to_tmp_dir_and_copy_fixtures,
):
    os.remove("pipelines.yml")

    result = CliRunner().invoke(generate_config)

    assert result.exit_code == 1
    assert "Error: There is no pipelines.yml" in result.output


def test_pipeline_generate_pipeline_yml_invalid_fails_with_message(
    switch_to_tmp_dir_and_copy_fixtures,
):
    with open("pipelines.yml", "w") as fh:
        print("{invalid data", file=fh)

    result = CliRunner().invoke(generate_config)

    assert result.exit_code == 1
    assert "Error: The pipelines.yml file is invalid" in result.output


def test_pipeline_generate_with_no_bootstrap_yml_fails_with_message(
    switch_to_tmp_dir_and_copy_fixtures,
):
    os.remove("bootstrap.yml")

    result = CliRunner().invoke(generate_config)

    assert result.exit_code == 1
    assert "Error: There is no bootstrap.yml" in result.output


def test_pipeline_generate_bootstrap_yml_invalid_fails_with_message(
    switch_to_tmp_dir_and_copy_fixtures,
):
    with open("bootstrap.yml", "w") as fh:
        print("{invalid data", file=fh)

    result = CliRunner().invoke(generate_config)

    assert result.exit_code == 1
    assert "Error: The bootstrap.yml file is invalid" in result.output


def assert_yaml_in_output_file_matches_expected(output_file, expected_file):
    def get_yaml(content):
        return yaml.safe_load(content)

    actual_content = output_file.read_text()
    expected_content = expected_file.read_text()

    assert actual_content.partition("\n")[0].strip() == expected_content.partition("\n")[0].strip()
    assert get_yaml(actual_content) == get_yaml(expected_content)


def setup_output_file_paths(tmp_path):
    output_dir = tmp_path / "copilot/pipelines/test-app-environments"
    buildspec = output_dir / "buildspec.yml"
    manifest = output_dir / "manifest.yml"
    cfn_patch = output_dir / "overrides" / "cfn.patches.yml"
    return buildspec, cfn_patch, manifest


def setup_git_repository():
    subprocess.run(["git", "init"])
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:uktrade/test-app.git"])


@fixture
def switch_to_tmp_dir_and_copy_fixtures(tmp_path):
    os.chdir(tmp_path)
    shutil.copy(FIXTURES_DIR / "valid_bootstrap_config.yml", "bootstrap.yml")
    shutil.copy(FIXTURES_DIR / "pipeline/pipelines.yml", "pipelines.yml")

    return tmp_path