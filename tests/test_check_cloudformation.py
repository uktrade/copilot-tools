from unittest.mock import patch

import pytest
from click.testing import CliRunner

import commands
from commands.check_cloudformation import check_cloudformation as check_cloudformation_command, valid_checks


class TestCheckCloudformationCommand:
    @pytest.fixture
    def valid_checks_dict(self):
        return {
            "all": lambda: None,
            "one": lambda: "Check one output",
            "two": lambda: "Check two output",
        }

    @patch("commands.check_cloudformation.valid_checks")
    def test_exit_if_no_check_specified(self, valid_checks_mock, valid_checks_dict):
        runner = CliRunner()
        valid_checks_mock.return_value = valid_checks_dict

        result = runner.invoke(check_cloudformation_command)

        assert result.exit_code == 2
        assert result.output.__contains__("Error: Missing argument 'CHECK'")

    @patch("commands.check_cloudformation.valid_checks")
    def test_exit_if_invalid_check_specified(self, valid_checks_mock, valid_checks_dict):
        runner = CliRunner()
        valid_checks_mock.return_value = valid_checks_dict

        result = runner.invoke(check_cloudformation_command, ["does-not-exist"])

        assert result.exit_code == 1
        assert isinstance(result.exception, ValueError)
        assert str(result.exception).__contains__("Invalid value (does-not-exist) for 'CHECK'")

    test_data = [
        ("one", "Check one output"),
        ("two", "Check two output"),
    ]

    @patch("commands.check_cloudformation.valid_checks")
    @pytest.mark.parametrize("requested_check, expected_check_output", test_data)
    def test_runs_specific_check_when_given_check(
            self,
            valid_checks_mock,
            valid_checks_dict,
            requested_check,
            expected_check_output
    ):
        runner = CliRunner()
        valid_checks_mock.return_value = valid_checks_dict

        result = runner.invoke(check_cloudformation_command, [requested_check])

        assert result.exit_code == 0
        assert result.output.__contains__(f"Running {requested_check} check")
        assert result.output.__contains__(expected_check_output)

    @patch("commands.check_cloudformation.valid_checks")
    def test_runs_all_checks_when_given_all(self, valid_checks_mock, valid_checks_dict):
        runner = CliRunner()
        valid_checks_mock.return_value = valid_checks_dict

        result = runner.invoke(check_cloudformation_command, ["all"])

        assert result.exit_code == 0
        assert result.output.__contains__("Running all checks")
        assert result.output.__contains__("Check one output")
        assert result.output.__contains__("Check two output")