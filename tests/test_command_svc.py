import uuid
from unittest.mock import patch

import botocore.errorfactory
from click.testing import CliRunner

from dbt_copilot_helper.commands.svc import deploy


@patch("boto3.client")
@patch("subprocess.call")
def test_svc_deploy_with_env_name_repository_and_image_tag_deploys_image_tag(
    subprocess_call, mock_boto_client
):
    """Test that given an env, name and image tag, copilot svc deploy is called
    with values to deploy the specified image to the environment's service."""

    branch_name, commit_hash, env, name, repository = set_up_test_variables()
    mock_describe_images_return_tags(branch_name, commit_hash, mock_boto_client)

    CliRunner().invoke(
        deploy,
        [
            "--env",
            env,
            "--name",
            name,
            "--repository",
            repository,
            "--image-tag",
            f"commit-{commit_hash}",
        ],
    )

    mock_boto_client.describe_images.assert_called_once()
    subprocess_call.assert_called_once_with(
        f"IMAGE_TAG=commit-{commit_hash} copilot svc deploy --env {env} --name {name}",
        shell=True,
    )


@patch("boto3.client")
@patch("subprocess.call")
def test_svc_deploy_with_latest_deploys_commit_tag_of_latest_image(
    subprocess_call, mock_boto_client
):
    """Test that given the image tag latest, copilot svc deploy is called with
    the unique commit tag of the image currently tagged latest."""

    branch_name, commit_hash, env, name, repository = set_up_test_variables()
    mock_describe_images_return_tags(branch_name, commit_hash, mock_boto_client)

    CliRunner().invoke(
        deploy,
        ["--env", env, "--name", name, "--repository", repository, "--image-tag", "latest"],
    )

    mock_boto_client.describe_images.assert_called_once()
    subprocess_call.assert_called_once_with(
        f"IMAGE_TAG=commit-{commit_hash} copilot svc deploy --env {env} --name {name}",
        shell=True,
    )


@patch("boto3.client")
@patch("subprocess.call")
def test_svc_deploy_with__no_image_tag_deploys_commit_tag_of_latest_image(
    subprocess_call, mock_boto_client
):
    """Test that given no image tag, copilot svc deploy is called with the
    unique tag of the image currently tagged latest."""

    branch_name, commit_hash, env, name, repository = set_up_test_variables()
    mock_describe_images_return_tags(branch_name, commit_hash, mock_boto_client)

    CliRunner().invoke(
        deploy,
        ["--env", env, "--name", name, "--repository", repository],
    )

    mock_boto_client.describe_images.assert_called_once()
    subprocess_call.assert_called_once_with(
        f"IMAGE_TAG=commit-{commit_hash} copilot svc deploy --env {env} --name {name}",
        shell=True,
    )


@patch("boto3.client")
def test_svc_deploy_with_nonexistent_image_tag_fails_with_message(mock_boto_client):
    """Test that given an image tag which does not exist, it fails with a
    helpful message."""

    branch_name, commit_hash, env, name, repository = set_up_test_variables()
    mock_describe_images_image_not_found(mock_boto_client)
    expected_tag = f"commit-{commit_hash}"

    result = CliRunner().invoke(
        deploy,
        ["--env", env, "--name", name, "--repository", repository, "--image-tag", expected_tag],
    )

    assert result.exit_code == 1
    assert f"""No image exists with the tag "{expected_tag}".""" in result.stdout


@patch("boto3.client")
def test_svc_deploy_with_latest_but_no_commit_tag_fails_with_message(mock_boto_client):
    """Test that given the image tag latest, where the image tagged latest has
    no commit tag, it fails with a helpful message."""

    branch_name, commit_hash, env, name, repository = set_up_test_variables()
    commit_hash = None
    mock_describe_images_return_tags(branch_name, commit_hash, mock_boto_client)

    result = CliRunner().invoke(
        deploy,
        ["--env", env, "--name", name, "--repository", repository, "--image-tag", "latest"],
    )

    assert result.exit_code == 1
    assert """The image tagged "latest" does not have a commit tag.""" in result.stdout

    # TODO: Pass other AWS Copilot flags through...?


def mock_describe_images_return_tags(branch_name, commit_hash, mock_boto_client):
    mock_boto_client.return_value = mock_boto_client
    image_tags = [
        f"commit-{commit_hash}",
        f"branch-{branch_name}",
        "latest",
    ]
    if not commit_hash:
        del image_tags[0]
    mock_boto_client.describe_images.return_value = {"imageDetails": [{"imageTags": image_tags}]}


def mock_describe_images_image_not_found(mock_boto_client):
    client_exceptions_factory = botocore.errorfactory.ClientExceptionsFactory()
    exception = client_exceptions_factory.create_client_exceptions(
        botocore.session.get_session().get_service_model("ecr")
    ).ImageNotFoundException
    mock_boto_client.return_value.exceptions.ImageNotFoundException = exception
    mock_boto_client.return_value.describe_images.side_effect = exception(
        {
            "Error": {
                "Code": "ImageNotFoundException",
                "Message": "The image requested does not exist in the specified repository.",
            },
        },
        "DescribeImages",
    )


def set_up_test_variables():
    hex_string = uuid.uuid4().hex[:7]
    commit_hash = f"{hex_string}"
    branch_name = "does-not-matter"
    env = f"env{hex_string}"
    name = f"name{hex_string}"
    repository = f"repo{hex_string}"
    return branch_name, commit_hash, env, name, repository
