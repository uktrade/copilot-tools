import json

import boto3
import psycopg2
import requests
from botocore.exceptions import ClientError


def drop_user(cursor, username):
    cursor.execute(f"SELECT * FROM pg_catalog.pg_user WHERE usename = '{username}'")

    if cursor.fetchone() is not None:
        cursor.execute(f"GRANT {username} TO postgres")
        cursor.execute(f"DROP OWNED BY {username}")
        cursor.execute(f"DROP USER {username}")


def create_db_user(conn, cursor, username, password, permissions):
    drop_user(cursor, username)

    cursor.execute(f"CREATE USER {username} WITH ENCRYPTED PASSWORD '%s'" % password)
    cursor.execute(f"GRANT {username} to postgres;")
    cursor.execute(f"GRANT {', '.join(permissions)} ON ALL TABLES IN SCHEMA public TO {username};")
    cursor.execute(
        f"ALTER DEFAULT PRIVILEGES FOR USER {username} IN SCHEMA public GRANT {', '.join(permissions)} ON TABLES TO {username};"
    )
    conn.commit()


def create_or_update_user_secret(ssm, user_secret_name, user_secret_string, event):
    user_secret_description = event["ResourceProperties"]["SecretDescription"]
    copilot_application = event["ResourceProperties"]["CopilotApplication"]
    copilot_environment = event["ResourceProperties"]["CopilotEnvironment"]

    user_secret = None

    try:
        user_secret = ssm.put_parameter(
            Name=user_secret_name,
            Description=user_secret_description,
            Value=json.dumps(user_secret_string),
            Tags=[
                {
                    "Key": "custom:cloudformation:stack-name",
                    "Value": event["StackId"].split("/")[1],
                },
                {"Key": "custom:cloudformation:logical-id", "Value": event["LogicalResourceId"]},
                {"Key": "custom:cloudformation:stack-id", "Value": event["StackId"]},
                {"Key": "copilot-application", "Value": copilot_application},
                {"Key": "copilot-environment", "Value": copilot_environment},
            ],
            Type="String",
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ParameterAlreadyExists":
            user_secret = ssm.put_parameter(
                Name=user_secret_name,
                Description=user_secret_description,
                Value=json.dumps(user_secret_string),
                Overwrite=True,
            )

    return user_secret


# borrowed from https://github.com/awslabs/aws-cloudformation-templates/blob/master/aws/services/CloudFormation/MacrosExamples/StackMetrics/lambda/cfnresponse.py
# tweaked to use requests library
def send(
    event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False, reason=None
):
    responseUrl = event["ResponseURL"]

    print(responseUrl)

    responseBody = {}
    responseBody["Status"] = responseStatus
    responseBody["Reason"] = (
        reason or "See the details in CloudWatch Log Stream: " + context.log_stream_name
    )
    responseBody["PhysicalResourceId"] = physicalResourceId or context.log_stream_name
    responseBody["StackId"] = event["StackId"]
    responseBody["RequestId"] = event["RequestId"]
    responseBody["LogicalResourceId"] = event["LogicalResourceId"]
    responseBody["NoEcho"] = noEcho
    responseBody["Data"] = responseData

    json_responseBody = json.dumps(responseBody)

    print("Response body:\n" + json_responseBody)

    headers = {"content-type": "", "content-length": str(len(json_responseBody))}

    try:
        response = requests.put(
            responseUrl, data=json_responseBody.encode("utf-8"), headers=headers
        )
        print("Status code: " + response.reason)
    except Exception as e:
        print("send(..) failed executing requests.put(..): " + str(e))


def handler(event, context):
    print("REQUEST RECEIVED:\n" + json.dumps(event))

    db_master_user_secret = event["ResourceProperties"]["MasterUserSecret"]
    user_secret_name = event["ResourceProperties"]["SecretName"]
    username = event["ResourceProperties"]["Username"]
    user_permissions = event["ResourceProperties"]["Permissions"]

    secrets_manager = boto3.client("secretsmanager")
    ssm = boto3.client("ssm")

    master_user = json.loads(
        secrets_manager.get_secret_value(SecretId=db_master_user_secret)["SecretString"]
    )

    user_password = secrets_manager.get_random_password(
        PasswordLength=16,
        ExcludeCharacters='[]{}()"@/\;=?&`><:|#',
        ExcludePunctuation=True,
        IncludeSpace=False,
    )["RandomPassword"]

    user_secret_string = {
        "username": username,
        "password": user_password,
        "engine": master_user["engine"],
        "port": master_user["port"],
        "dbname": master_user["dbname"],
        "host": master_user["host"],
    }

    if "dbClusterIdentifier" in master_user.keys():
        user_secret_string["dbClusterIdentifier"] = master_user["dbClusterIdentifier"]

    if "dbInstanceIdentifier" in master_user.keys():
        user_secret_string["dbInstanceIdentifier"] = master_user["dbInstanceIdentifier"]

    conn = psycopg2.connect(
        dbname=master_user["dbname"],
        user=master_user["username"],
        password=master_user["password"],
        host=master_user["host"],
        port=master_user["port"],
    )

    cursor = conn.cursor()

    response = {"Status": "SUCCESS"}

    try:
        match event["RequestType"]:
            case "Create":
                create_db_user(conn, cursor, username, user_password, user_permissions)

                response = {
                    **response,
                    "Data": create_or_update_user_secret(
                        ssm, user_secret_name, user_secret_string, event
                    ),
                }
            case "Update":
                create_db_user(conn, cursor, username, user_password, user_permissions)

                response = {
                    **response,
                    "Data": create_or_update_user_secret(
                        ssm, user_secret_name, user_secret_string, event
                    ),
                }
            case "Delete":
                drop_user(cursor, username)

                response = {**response, "Data": ssm.delete_parameter(Name=user_secret_name)}
            case _:
                response = {
                    "Status": "FAILED",
                    "Data": {"Error": f"""Invalid requestType of '${event["RequestType"]}'"""},
                }
    except Exception as e:
        response = {"Status": "FAILED", "Data": {"Error": str(e)}}

    cursor.close()
    conn.close()

    print(json.dumps(response, default=str))
    send(event, context, response["Status"], response["Data"], event["LogicalResourceId"])
