import json
import unittest
from multiprocessing import context
from unittest.mock import MagicMock
from unittest.mock import patch

import boto3
import pytest
import responses
from moto import mock_resourcegroupstaggingapi
from moto import mock_secretsmanager
from moto import mock_ssm
from parameterized import parameterized

from dbt_platform_helper.custom_resources.app_user import create_db_user
from dbt_platform_helper.custom_resources.app_user import create_or_update_user_secret
from dbt_platform_helper.custom_resources.app_user import drop_user
from dbt_platform_helper.custom_resources.app_user import handler
from dbt_platform_helper.custom_resources.app_user import send


class TestAppUserCustomResource(unittest.TestCase):
    def setUp(self):
        self.cursor = MagicMock()

    @classmethod
    def setUpClass(cls):
        cls.secret_name = "test-secret-name"
        cls.secret_string = '{"engine": "postgres", "port": 5432, "dbname": "main", "host": "test-host", "username": "random-user", "password": "password123"}'
        cls.event = {
            "ResourceProperties": {
                "SecretName": cls.secret_name,
                "SecretDescription": "used for testing",
                "Username": "test-user",
                "Permissions": ["SELECT"],
                "CopilotApplication": "test-app",
                "CopilotEnvironment": "test",
            },
            "LogicalResourceId": "123LogicalResourceId",
            "StackId": "123/TestStackId",
        }
        cls.context = MagicMock()
        cls.conn = MagicMock()
        cls.cursor = MagicMock()

    @pytest.fixture(autouse=True)
    def capsys(self, capsys):
        self.capsys = capsys

    def test_drop_user(self):
        self.cursor.fetchone.return_value = ("user_info",)

        drop_user(self.cursor, "test_user")

        self.cursor.execute.assert_any_call(
            "SELECT * FROM pg_catalog.pg_user WHERE usename = 'test_user'"
        )
        self.cursor.execute.assert_any_call("GRANT test_user TO postgres")
        self.cursor.execute.assert_any_call("DROP OWNED BY test_user")
        self.cursor.execute.assert_any_call("DROP USER test_user")

    def test_drop_user_no_user(self):
        self.cursor.fetchone.return_value = None

        drop_user(self.cursor, "nonexistent_user")

        self.cursor.execute.assert_called_once_with(
            "SELECT * FROM pg_catalog.pg_user WHERE usename = 'nonexistent_user'"
        )

    def test_create_db_user(self):
        self.cursor.fetchone.return_value = ("user_info",)
        conn = MagicMock()
        username = "test_user"
        password = "test_password"
        permissions = ["SELECT", "INSERT"]

        create_db_user(conn, self.cursor, username, password, permissions)

        self.cursor.execute.assert_any_call(f"DROP USER {username}")
        self.cursor.execute.assert_any_call(
            f"CREATE USER {username} WITH ENCRYPTED PASSWORD '{password}'"
        )
        self.cursor.execute.assert_any_call(f"GRANT {username} to postgres;")
        self.cursor.execute.assert_any_call(
            f"GRANT {', '.join(permissions)} ON ALL TABLES IN SCHEMA public TO {username};"
        )
        self.cursor.execute.assert_any_call(
            f"ALTER DEFAULT PRIVILEGES FOR USER {username} IN SCHEMA public GRANT {', '.join(permissions)} ON TABLES TO {username};"
        )

        conn.commit.assert_called_once()

    @mock_resourcegroupstaggingapi
    @mock_ssm
    def test_create_or_update_user_secret(self):
        ssm = boto3.client("ssm")
        user_secret_name = "/test/secret"
        user_secret_string = {"username": "test_user", "password": "test_password"}

        response = create_or_update_user_secret(
            ssm, user_secret_name, user_secret_string, self.event
        )

        parameter = ssm.get_parameter(Name=user_secret_name)["Parameter"]
        parameter_described = ssm.describe_parameters()["Parameters"][0]

        assert response["Version"] == 1
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
        assert parameter["Name"] == user_secret_name
        assert parameter["Value"] == json.dumps(user_secret_string)
        assert parameter_described["Description"] == "used for testing"

    @mock_ssm
    def test_create_or_update_user_secret_overwrites(self):
        user_secret_name = "/test/secret"
        user_secret_string = {"username": "test_user", "password": "test_password"}
        ssm = boto3.client("ssm")
        ssm.put_parameter(Name=user_secret_name, Value="blah", Type="String")

        create_or_update_user_secret(ssm, user_secret_name, user_secret_string, self.event)

        parameter = ssm.get_parameter(Name=user_secret_name)["Parameter"]

        assert parameter["Version"] == 2
        assert parameter["Value"] == json.dumps(user_secret_string)

    @responses.activate
    def test_send(self):
        event = {
            "ResponseURL": "https://test.url",
            "StackId": 123,
            "RequestId": 1234,
            "LogicalResourceId": 12345,
        }
        context = MagicMock()
        context.log_stream_name = "test-log-stream"
        responseStatus = 200
        responseData = {"some": "test data"}
        physicalResourceId = 123456
        noEcho = True
        reason = "Success"
        response = responses.Response(method="PUT", url="https://test.url")
        responses.add(response)

        send(event, context, responseStatus, responseData, physicalResourceId, noEcho, reason)

        assert len(responses.calls) == 1
        assert responses.calls[0].request.url == "https://test.url/"
        assert responses.calls[0].request.headers["content-type"] == ""
        assert (
            responses.calls[0].request.body.decode()
            == '{"Status": 200, "Reason": "Success", "PhysicalResourceId": 123456, "StackId": 123, "RequestId": 1234, "LogicalResourceId": 12345, "NoEcho": true, "Data": {"some": "test data"}}'
        )

    @responses.activate
    def test_send_exception(self):
        event = {
            "ResponseURL": "https://test.url",
            "StackId": 123,
            "RequestId": 1234,
            "LogicalResourceId": 12345,
        }
        context = MagicMock()
        context.log_stream_name = "test-log-stream"
        responseStatus = 200
        responseData = {"some": "test data"}
        physicalResourceId = 123456
        noEcho = True
        reason = "Success"
        response = responses.Response(
            method="PUT", url="https://test.url", body=Exception("summut went wrong")
        )
        responses.add(response)

        send(event, context, responseStatus, responseData, physicalResourceId, noEcho, reason)

        captured = self.capsys.readouterr()

        assert "send(..) failed executing requests.put(..): summut went wrong" in captured.out

    @parameterized.expand(["Create", "Update"])
    @patch("dbt_platform_helper.custom_resources.app_user.create_db_user")
    @patch("dbt_platform_helper.custom_resources.app_user.send")
    @patch("dbt_platform_helper.custom_resources.app_user.psycopg2.connect")
    @mock_secretsmanager
    @mock_ssm
    def test_handler(self, request_type, mock_connect, mock_send, mock_create_db_user):
        secretsmanager = boto3.client("secretsmanager")
        secret_id = secretsmanager.create_secret(
            Name=self.secret_name, SecretString=self.secret_string
        )["ARN"]
        self.event["ResourceProperties"]["MasterUserSecret"] = secret_id
        self.event["RequestType"] = request_type
        mock_connect.return_value = self.conn
        self.conn.cursor = self.cursor

        handler(self.event, context)

        ssm = boto3.client("ssm")
        user_password = json.loads(ssm.get_parameter(Name=self.secret_name)["Parameter"]["Value"])[
            "password"
        ]
        mock_create_db_user.assert_called_once_with(
            self.conn, self.cursor(), "test-user", user_password, ["SELECT"]
        )

        captured = self.capsys.readouterr()
        data = json.loads(captured.out.split("\n")[2])["Data"]

        mock_send.assert_called_once_with(
            self.event, context, "SUCCESS", data, self.event["LogicalResourceId"]
        )

    @patch("dbt_platform_helper.custom_resources.app_user.drop_user")
    @patch("dbt_platform_helper.custom_resources.app_user.send")
    @patch("dbt_platform_helper.custom_resources.app_user.psycopg2.connect")
    @mock_secretsmanager
    @mock_ssm
    def test_handler_delete(self, mock_connect, mock_send, mock_drop_user):
        secretsmanager = boto3.client("secretsmanager")
        secret_id = secretsmanager.create_secret(
            Name=self.secret_name, SecretString=self.secret_string
        )["ARN"]
        ssm = boto3.client("ssm")
        ssm.put_parameter(Name=self.secret_name, Value="blah", Type="String")
        self.event["ResourceProperties"]["MasterUserSecret"] = secret_id
        self.event["RequestType"] = "Delete"
        mock_connect.return_value = self.conn
        self.conn.cursor = self.cursor

        handler(self.event, context)

        captured = self.capsys.readouterr()
        data = json.loads(captured.out.split("\n")[2])["Data"]

        mock_drop_user.assert_called_once_with(self.cursor(), "test-user")
        mock_send.assert_called_once_with(
            self.event, context, "SUCCESS", data, self.event["LogicalResourceId"]
        )
        assert len(ssm.describe_parameters()["Parameters"]) == 0

    @patch("dbt_platform_helper.custom_resources.app_user.send")
    @patch("dbt_platform_helper.custom_resources.app_user.psycopg2.connect")
    @mock_secretsmanager
    def test_handler_invalid_request_type(self, mock_connect, mock_send):
        secretsmanager = boto3.client("secretsmanager")
        secret_id = secretsmanager.create_secret(
            Name=self.secret_name, SecretString=self.secret_string
        )["ARN"]
        self.event["ResourceProperties"]["MasterUserSecret"] = secret_id
        self.event["RequestType"] = "Patch"
        mock_connect.return_value = self.conn
        self.conn.cursor = self.cursor

        handler(self.event, context)

        captured = self.capsys.readouterr()
        data = json.loads(captured.out.split("\n")[2])["Data"]

        mock_send.assert_called_once_with(
            self.event, context, "FAILED", data, self.event["LogicalResourceId"]
        )

    @patch("dbt_platform_helper.custom_resources.app_user.create_db_user", side_effect=Exception())
    @patch("dbt_platform_helper.custom_resources.app_user.send")
    @patch("dbt_platform_helper.custom_resources.app_user.psycopg2.connect")
    @mock_secretsmanager
    def test_handler_exception(self, mock_connect, mock_send, mock_create_db_user):
        secretsmanager = boto3.client("secretsmanager")
        secret_id = secretsmanager.create_secret(
            Name=self.secret_name, SecretString=self.secret_string
        )["ARN"]
        self.event["ResourceProperties"]["MasterUserSecret"] = secret_id
        self.event["RequestType"] = "Create"
        mock_connect.return_value = self.conn
        self.conn.cursor = self.cursor

        handler(self.event, context)

        captured = self.capsys.readouterr()
        data = json.loads(captured.out.split("\n")[2])["Data"]

        mock_send.assert_called_once_with(
            self.event, context, "FAILED", data, self.event["LogicalResourceId"]
        )
