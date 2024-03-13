import json
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import mock_open
from unittest.mock import patch

import boto3
import pytest
from moto import mock_ec2
from moto import mock_ecs
from moto import mock_elbv2
from moto import mock_ssm

from dbt_platform_helper.exceptions import ValidationException
from dbt_platform_helper.utils.aws import NoProfileForAccountIdError
from dbt_platform_helper.utils.aws import get_account_details
from dbt_platform_helper.utils.aws import get_aws_session_or_abort
from dbt_platform_helper.utils.aws import get_codestar_connection_arn
from dbt_platform_helper.utils.aws import get_load_balancer_domain_and_configuration
from dbt_platform_helper.utils.aws import get_profile_name_from_account_id
from dbt_platform_helper.utils.aws import get_public_repository_arn
from dbt_platform_helper.utils.aws import get_ssm_secrets
from dbt_platform_helper.utils.aws import set_ssm_param
from tests.platform_helper.conftest import mock_aws_client
from tests.platform_helper.conftest import mock_codestar_connections_boto_client
from tests.platform_helper.conftest import mock_ecr_public_repositories_boto_client
from tests.platform_helper.conftest import mock_get_caller_identity

HYPHENATED_APPLICATION_NAME = "hyphenated-application-name"
ALPHANUMERIC_ENVIRONMENT_NAME = "alphanumericenvironmentname123"
ALPHANUMERIC_SERVICE_NAME = "alphanumericservicename123"
COPILOT_IDENTIFIER = "c0PIlotiD3ntIF3r"
CLUSTER_NAME_SUFFIX = f"Cluster-{COPILOT_IDENTIFIER}"
SERVICE_NAME_SUFFIX = f"Service-{COPILOT_IDENTIFIER}"


def test_get_aws_session_or_abort_profile_not_configured(clear_session_cache, capsys):
    with pytest.raises(SystemExit):
        get_aws_session_or_abort("foo")

    captured = capsys.readouterr()

    assert """AWS profile "foo" is not configured.""" in captured.out


def get_mock_session(name):
    session = Mock(name=name)
    client = Mock(name=f"client-mock-for-{name}")
    session.client.return_value = client
    client.get_caller_identity.return_value = {"Account": "account", "UserId": "user"}
    client.list_account_aliases.return_value = {"AccountAliases": "account", "UserId": "user"}

    return session


@patch("boto3.session.Session")
def test_get_aws_session_caches_sessions_per_profile(mock_session):
    mock_session.side_effect = (get_mock_session("one"), get_mock_session("two"))
    session1 = get_aws_session_or_abort()
    session2 = get_aws_session_or_abort()

    session3 = get_aws_session_or_abort("my-profile")
    session4 = get_aws_session_or_abort("my-profile")

    assert session1 is session2
    assert session3 is session4
    assert session1 is not session4


@patch("dbt_platform_helper.utils.aws.get_aws_session_or_abort")
def test_get_ssm_secrets(mock_get_aws_session_or_abort):
    client = mock_aws_client(mock_get_aws_session_or_abort)
    client.get_parameters_by_path.return_value = {
        "Parameters": [
            {
                "Name": "/copilot/test-application/development/secrets/TEST_SECRET",
                "Description": "A test parameter",
                "Value": "test value",
                "Type": "SecureString",
            }
        ]
    }

    result = get_ssm_secrets("test-application", "development")

    assert result == [("/copilot/test-application/development/secrets/TEST_SECRET", "test value")]


@pytest.mark.parametrize(
    "overwrite, exists",
    [(False, False), (False, True)],
)
@mock_ssm
@patch("dbt_platform_helper.utils.aws.get_aws_session_or_abort")
def test_set_ssm_param(mock_get_aws_session_or_abort, overwrite, exists):
    mocked_ssm = boto3.client("ssm")
    mock_aws_client(mock_get_aws_session_or_abort, mocked_ssm)

    set_ssm_param(
        "test-application",
        "development",
        "/copilot/test-application/development/secrets/TEST_SECRET",
        "random value",
        overwrite,
        exists,
        "Created for testing purposes.",
    )

    params = dict(
        Path="/copilot/test-application/development/secrets/",
        Recursive=False,
        WithDecryption=True,
        MaxResults=10,
    )

    result = mocked_ssm.get_parameters_by_path(**params)["Parameters"][0]

    expected_response = {
        "ARN": "arn:aws:ssm:eu-west-2:123456789012:parameter/copilot/test-application/development/secrets/TEST_SECRET",
        "Name": "/copilot/test-application/development/secrets/TEST_SECRET",
        "Type": "SecureString",
        "Value": "random value",
    }

    # assert result is a superset of expected_response
    assert result.items() >= expected_response.items()


@mock_ssm
@patch("dbt_platform_helper.utils.aws.get_aws_session_or_abort")
def test_set_ssm_param_with_existing_secret(mock_get_aws_session_or_abort):
    mocked_ssm = boto3.client("ssm")
    mock_aws_client(mock_get_aws_session_or_abort, mocked_ssm)

    mocked_ssm.put_parameter(
        Name="/copilot/test-application/development/secrets/TEST_SECRET",
        Description="A test parameter",
        Value="test value",
        Type="SecureString",
    )

    params = dict(
        Path="/copilot/test-application/development/secrets/",
        Recursive=False,
        WithDecryption=True,
        MaxResults=10,
    )

    assert mocked_ssm.get_parameters_by_path(**params)["Parameters"][0]["Value"] == "test value"

    set_ssm_param(
        "test-application",
        "development",
        "/copilot/test-application/development/secrets/TEST_SECRET",
        "overwritten value",
        True,
        True,
        "Created for testing purposes.",
    )

    result = mocked_ssm.get_parameters_by_path(**params)["Parameters"][0]["Value"]

    assert result != "test value"
    assert result == "overwritten value"


@mock_ssm
@patch("dbt_platform_helper.utils.aws.get_aws_session_or_abort")
def test_set_ssm_param_with_overwrite_but_not_exists(mock_get_aws_session_or_abort):
    mocked_ssm = boto3.client("ssm")
    mock_aws_client(mock_get_aws_session_or_abort, mocked_ssm)

    mocked_ssm.put_parameter(
        Name="/copilot/test-application/development/secrets/TEST_SECRET",
        Description="A test parameter",
        Value="test value",
        Type="SecureString",
    )

    params = dict(
        Path="/copilot/test-application/development/secrets/",
        Recursive=False,
        WithDecryption=True,
        MaxResults=10,
    )

    assert mocked_ssm.get_parameters_by_path(**params)["Parameters"][0]["Value"] == "test value"

    with pytest.raises(ValidationException) as exception:
        set_ssm_param(
            "test-application",
            "development",
            "/copilot/test-application/development/secrets/TEST_SECRET",
            "overwritten value",
            True,
            False,
            "Created for testing purposes.",
        )

    assert (
        """Arguments "overwrite" is set to True, but "exists" is set to False."""
        == exception.value.args[0]
    )


@mock_ssm
@patch("dbt_platform_helper.utils.aws.get_aws_session_or_abort")
def test_set_ssm_param_tags(mock_get_aws_session_or_abort):
    mocked_ssm = boto3.client("ssm")
    mock_aws_client(mock_get_aws_session_or_abort, mocked_ssm)

    set_ssm_param(
        "test-application",
        "development",
        "/copilot/test-application/development/secrets/TEST_SECRET",
        "random value",
        False,
        False,
        "Created for testing purposes.",
    )

    parameters = mocked_ssm.describe_parameters(
        ParameterFilters=[
            {"Key": "tag:copilot-application", "Values": ["test-application"]},
            {"Key": "tag:copilot-environment", "Values": ["development"]},
        ]
    )["Parameters"]

    assert len(parameters) == 1
    assert parameters[0]["Name"] == "/copilot/test-application/development/secrets/TEST_SECRET"

    response = mocked_ssm.describe_parameters(ParameterFilters=[{"Key": "tag:copilot-application"}])

    assert len(response["Parameters"]) == 1
    assert {parameter["Name"] for parameter in response["Parameters"]} == {
        "/copilot/test-application/development/secrets/TEST_SECRET"
    }


@mock_ssm
@patch("dbt_platform_helper.utils.aws.get_aws_session_or_abort")
def test_set_ssm_param_tags_with_existing_secret(mock_get_aws_session_or_abort):
    mocked_ssm = boto3.client("ssm")
    mock_aws_client(mock_get_aws_session_or_abort, mocked_ssm)

    secret_name = "/copilot/test-application/development/secrets/TEST_SECRET"
    tags = [
        {"Key": "copilot-application", "Value": "test-application"},
        {"Key": "copilot-environment", "Value": "development"},
    ]

    mocked_ssm.put_parameter(
        Name=secret_name,
        Description="A test parameter",
        Value="test value",
        Type="SecureString",
        Tags=tags,
    )

    assert (
        tags
        == mocked_ssm.list_tags_for_resource(ResourceType="Parameter", ResourceId=secret_name)[
            "TagList"
        ]
    )

    set_ssm_param(
        "test-application",
        "development",
        secret_name,
        "random value",
        True,
        True,
        "Created for testing purposes.",
    )

    assert (
        tags
        == mocked_ssm.list_tags_for_resource(ResourceType="Parameter", ResourceId=secret_name)[
            "TagList"
        ]
    )


@patch("dbt_platform_helper.utils.aws.get_aws_session_or_abort")
@pytest.mark.parametrize(
    "connection_names, app_name, expected_arn",
    [
        [
            [
                "test-app-name",
            ],
            "test-app-name",
            f"arn:aws:codestar-connections:eu-west-2:1234567:connection/test-app-name",
        ],
        [
            [
                "test-app-name-1",
                "test-app-name-2",
                "test-app-name-3",
            ],
            "test-app-name-2",
            f"arn:aws:codestar-connections:eu-west-2:1234567:connection/test-app-name-2",
        ],
        [
            [
                "test-app-name",
            ],
            "test-app-name-2",
            None,
        ],
    ],
)
def test_get_codestar_connection_arn(
    mock_get_aws_session_or_abort, connection_names, app_name, expected_arn
):
    mock_codestar_connections_boto_client(mock_get_aws_session_or_abort, connection_names)

    result = get_codestar_connection_arn(app_name)

    assert result == expected_arn


@patch("dbt_platform_helper.utils.aws.get_aws_session_or_abort")
@pytest.mark.parametrize(
    "repository_uri, expected_arn",
    [
        ("public.ecr.aws/abc123/my/app", "arn:aws:ecr-public::000000000000:repository/my/app"),
        ("public.ecr.aws/abc123/my/app2", "arn:aws:ecr-public::000000000000:repository/my/app2"),
        ("public.ecr.aws/abc123/does-not/exist", None),
    ],
)
def test_get_public_repository_arn(mock_get_aws_session_or_abort, repository_uri, expected_arn):
    mock_ecr_public_repositories_boto_client(mock_get_aws_session_or_abort)

    result = get_public_repository_arn(repository_uri)

    assert result == expected_arn


@patch("dbt_platform_helper.utils.aws.get_aws_session_or_abort")
def test_get_account_id(mock_get_aws_session_or_abort):
    mock_get_caller_identity(mock_get_aws_session_or_abort)

    account_id, user_id = get_account_details()

    assert account_id == "000000000000"
    assert user_id == "abc123"


def test_get_account_id_passing_in_client():
    mock_client = MagicMock()
    mock_client.get_caller_identity.return_value = {"Account": "000000000001", "UserId": "abc456"}

    account_id, user_id = get_account_details(mock_client)

    assert account_id == "000000000001"
    assert user_id == "abc456"


def test_get_profile_name_from_account_id(fakefs):
    assert get_profile_name_from_account_id("000000000") == "development"
    assert get_profile_name_from_account_id("111111111") == "staging"
    assert get_profile_name_from_account_id("222222222") == "production"


def test_get_profile_name_from_account_id_with_no_matching_account(fakefs):
    with pytest.raises(NoProfileForAccountIdError) as error:
        get_profile_name_from_account_id("999999999")

    assert str(error.value) == "No profile found for account 999999999"


@mock_ecs
def test_get_load_balancer_domain_and_configuration_no_clusters(capfd):
    with pytest.raises(SystemExit):
        get_load_balancer_domain_and_configuration(
            boto3.Session(),
            HYPHENATED_APPLICATION_NAME,
            ALPHANUMERIC_ENVIRONMENT_NAME,
            ALPHANUMERIC_SERVICE_NAME,
        )

    out, _ = capfd.readouterr()

    assert (
        out == f"There are no clusters for environment {ALPHANUMERIC_ENVIRONMENT_NAME} of "
        f"application {HYPHENATED_APPLICATION_NAME} in AWS account default\n"
    )


@mock_ecs
def test_get_load_balancer_domain_and_configuration_no_services(capfd):
    boto3.Session().client("ecs").create_cluster(
        clusterName=f"{HYPHENATED_APPLICATION_NAME}-{ALPHANUMERIC_ENVIRONMENT_NAME}-{CLUSTER_NAME_SUFFIX}"
    )
    with pytest.raises(SystemExit):
        get_load_balancer_domain_and_configuration(
            boto3.Session(),
            HYPHENATED_APPLICATION_NAME,
            ALPHANUMERIC_ENVIRONMENT_NAME,
            ALPHANUMERIC_SERVICE_NAME,
        )

    out, _ = capfd.readouterr()

    assert (
        out == f"There are no services called {ALPHANUMERIC_SERVICE_NAME} for environment "
        f"{ALPHANUMERIC_ENVIRONMENT_NAME} of application {HYPHENATED_APPLICATION_NAME} "
        f"in AWS account default\n"
    )


@mock_elbv2
@mock_ec2
@mock_ecs
@pytest.mark.parametrize(
    "svc_name",
    [
        ALPHANUMERIC_SERVICE_NAME,
        "test",
        "test-service",
        "test-service-name",
    ],
)
def test_get_load_balancer_domain_and_configuration(tmp_path, svc_name):
    cluster_name = (
        f"{HYPHENATED_APPLICATION_NAME}-{ALPHANUMERIC_ENVIRONMENT_NAME}-{CLUSTER_NAME_SUFFIX}"
    )
    service_name = f"{HYPHENATED_APPLICATION_NAME}-{ALPHANUMERIC_ENVIRONMENT_NAME}-{svc_name}-{SERVICE_NAME_SUFFIX}"
    session = boto3.Session()
    mocked_vpc_id = session.client("ec2").create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    mocked_subnet_id = session.client("ec2").create_subnet(
        VpcId=mocked_vpc_id, CidrBlock="10.0.0.0/16"
    )["Subnet"]["SubnetId"]
    mocked_elbv2_client = session.client("elbv2")
    mocked_load_balancer_arn = mocked_elbv2_client.create_load_balancer(
        Name="foo", Subnets=[mocked_subnet_id]
    )["LoadBalancers"][0]["LoadBalancerArn"]
    target_group = mocked_elbv2_client.create_target_group(
        Name="foo", Protocol="HTTPS", Port=80, VpcId=mocked_vpc_id
    )
    target_group_arn = target_group["TargetGroups"][0]["TargetGroupArn"]
    mocked_elbv2_client.create_listener(
        LoadBalancerArn=mocked_load_balancer_arn,
        DefaultActions=[{"Type": "forward", "TargetGroupArn": target_group_arn}],
    )
    mocked_ecs_client = session.client("ecs")
    mocked_ecs_client.create_cluster(clusterName=cluster_name)
    mocked_ecs_client.create_service(
        cluster=cluster_name,
        serviceName=service_name,
        loadBalancers=[{"loadBalancerName": "foo", "targetGroupArn": target_group_arn}],
    )
    mocked_service_manifest_contents = {
        "environments": {ALPHANUMERIC_ENVIRONMENT_NAME: {"http": {"alias": "somedomain.tld"}}}
    }
    open_mock = mock_open(read_data=json.dumps(mocked_service_manifest_contents))

    with patch("dbt_platform_helper.utils.aws.open", open_mock):
        domain_name, load_balancer_configuration = get_load_balancer_domain_and_configuration(
            boto3.Session(), HYPHENATED_APPLICATION_NAME, ALPHANUMERIC_ENVIRONMENT_NAME, svc_name
        )

    open_mock.assert_called_once_with(f"./copilot/{svc_name}/manifest.yml", "r")
    assert domain_name == "somedomain.tld"
    assert load_balancer_configuration["LoadBalancerArn"] == mocked_load_balancer_arn
    assert load_balancer_configuration["LoadBalancerName"] == "foo"
    assert load_balancer_configuration["VpcId"] == mocked_vpc_id
    assert load_balancer_configuration["AvailabilityZones"][0]["SubnetId"] == mocked_subnet_id


@pytest.mark.parametrize(
    "svc_name, content, exp_error",
    [
        ("testsvc1", """environments: {test: {http: {alias: }}}""", "No domains found"),
        ("testsvc2", """environments: {test: {http: }}""", "No domains found"),
        (
            "testsvc3",
            """environments: {not_test: {http: {alias: test.com}}}""",
            "Environment test not found",
        ),
    ],
)
@patch("dbt_platform_helper.utils.aws.get_load_balancer_configuration", return_value="test.com")
def test_get_load_balancer_domain_and_configuration_no_domain(
    get_load_balancer_configuration, fakefs, capsys, svc_name, content, exp_error
):
    fakefs.create_file(
        f"copilot/{svc_name}/manifest.yml",
        contents=content,
    )
    with pytest.raises(SystemExit):
        get_load_balancer_domain_and_configuration("test", "testapp", "test", svc_name)
    assert (
        capsys.readouterr().out
        == f"{exp_error}, please check the ./copilot/{svc_name}/manifest.yml file\n"
    )
