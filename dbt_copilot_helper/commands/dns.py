#!/usr/bin/env python

import os
import time
from typing import Tuple

import click
import yaml
from boto3 import Session

from dbt_copilot_helper.utils.aws import check_response
from dbt_copilot_helper.utils.aws import get_aws_session_or_abort
from dbt_copilot_helper.utils.click import ClickDocOptGroup
from dbt_copilot_helper.utils.files import ensure_cwd_is_repo_root
from dbt_copilot_helper.utils.messages import abort_with_error
from dbt_copilot_helper.utils.versioning import (
    check_copilot_helper_version_needs_update,
)

# To do
# -----
# Check user has logged into the aws accounts before scanning the accounts
# When adding records from parent to subdomain, if ok, it then should remove them from parent domain
# (run a test before removing)

# Base domain depth
MAX_DOMAIN_DEPTH = 2
AWS_CERT_REGION = "eu-west-2"


def _wait_for_certificate_validation(acm_client, certificate_arn, sleep_time=10, timeout=600):
    click.secho(f"Waiting up to {timeout} seconds for certificate to be validated...", fg="yellow")
    status = acm_client.describe_certificate(CertificateArn=certificate_arn)["Certificate"][
        "Status"
    ]
    elapsed_time = 0
    while status == "PENDING_VALIDATION":
        if elapsed_time >= timeout:
            raise Exception(
                f"Timeout ({timeout}s) reached for certificate validation, might be worth checking things in the AWS Console"
            )
        click.echo(
            click.style(f"{certificate_arn}", fg="white", bold=True)
            + click.style(
                f": Waiting {sleep_time}s for validation, {elapsed_time}s elapsed, {timeout - elapsed_time}s until we give up...",
                fg="yellow",
            ),
        )
        time.sleep(sleep_time)
        status = acm_client.describe_certificate(CertificateArn=certificate_arn)["Certificate"][
            "Status"
        ]
        elapsed_time += sleep_time

    if status == "ISSUED":
        click.secho("Certificate validated...", fg="green")
    else:
        raise Exception(f"""Certificate validation failed with the status "{status}".""")


def create_cert(client, domain_client, domain, base_len):
    for cert in _certs_for_domain(client, domain):
        if cert["Status"] == "ISSUED":
            click.secho("Certificate already exists, do not need to create.", fg="green")
            return cert["CertificateArn"]
        else:
            click.secho(
                f"Certificate already exists but appears to be invalid (in status '{cert['Status']}'), deleting the old cert.",
                fg="yellow",
            )
            client.delete_certificate(CertificateArn=cert["CertificateArn"])

    if not click.confirm(
        click.style("Creating Certificate for ", fg="yellow")
        + click.style(f"{domain}\n", fg="white", bold=True)
        + click.style("Do you want to continue?", fg="yellow"),
    ):
        exit()

    domain_to_create = _get_domain_to_create(base_len, domain)

    arn = _request_cert(client, domain)

    # Create DNS validation records
    cert_record = _get_certificate_record(arn, client)
    domain_id = _get_domain_id(domain_client, domain_to_create)

    if not domain_id:
        # Will got here more than once during manual testing,
        # it might be a race condition we need to handle better
        click.secho(
            f"Unable to find Domain ID for {domain_to_create} in the hosted zones",
            fg="red",
            bold=True,
        )
        exit(1)

    # Add NS records of subdomain to parent
    click.secho(domain_id, fg="yellow")

    if not click.confirm(
        click.style("Updating DNS record for certificate ", fg="yellow")
        + click.style(f"{domain}", fg="white", bold=True)
        + click.style(" with value ", fg="yellow")
        + click.style(f"""{cert_record["Value"]}\n""", fg="white", bold=True)
        + click.style("Do you want to continue?", fg="yellow"),
    ):
        exit()

    _create_resource_records(cert_record, domain_client, domain_id)

    # Wait for certificate to get to validation state before continuing.
    # Will upped the timeout from 600 to 1200 because he repeatedly saw it timeout at 600
    # and wants to give it a chance to take longer in case that's all that's wrong.
    _wait_for_certificate_validation(client, certificate_arn=arn, timeout=1200)

    return arn


def _create_resource_records(cert_record, domain_client, domain_id):
    domain_client.change_resource_record_sets(
        HostedZoneId=domain_id,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "CREATE",
                    "ResourceRecordSet": {
                        "Name": cert_record["Name"],
                        "Type": cert_record["Type"],
                        "TTL": 300,
                        "ResourceRecords": [
                            {"Value": cert_record["Value"]},
                        ],
                    },
                },
            ],
        },
    )


def _get_domain_id(domain_client, domain_to_create):
    click.secho(f"Looking for ID of domain {domain_to_create}...", fg="yellow")
    hosted_zones = domain_client.list_hosted_zones_by_name()["HostedZones"]

    for hz in hosted_zones:
        if hz["Name"] == domain_to_create:
            return hz["Id"]


def _get_domain_to_create(base_len, domain):
    parts = domain.split(".")
    # We only want to create domains max 2 deep so remove all sub domains in excess
    parts_to_remove = len(parts) - base_len - MAX_DOMAIN_DEPTH
    domain_to_create = ".".join(parts[parts_to_remove:]) + "."
    click.secho(domain_to_create, fg="yellow")
    return domain_to_create


def _certs_for_domain(client, domain):
    # Check if cert is present.
    cert_list = client.list_certificates(
        CertificateStatuses=[
            "PENDING_VALIDATION",
            "ISSUED",
            "INACTIVE",
            "EXPIRED",
            "VALIDATION_TIMED_OUT",
            "REVOKED",
            "FAILED",
        ],
        MaxItems=500,
    )["CertificateSummaryList"]
    certs_for_domain = [cert for cert in cert_list if cert["DomainName"] == domain]
    return certs_for_domain


def _get_certificate_record(arn, client):
    # Need a pause for it to populate the DNS resource records
    cert_description = client.describe_certificate(CertificateArn=arn)
    while (
        cert_description["Certificate"].get("DomainValidationOptions") is None
        or cert_description["Certificate"]["DomainValidationOptions"][0].get("ResourceRecord")
        is None
    ):
        click.secho("Waiting for DNS records...", fg="yellow")
        time.sleep(2)
        cert_description = client.describe_certificate(CertificateArn=arn)
    return cert_description["Certificate"]["DomainValidationOptions"][0]["ResourceRecord"]


def _request_cert(client, domain):
    cert_response = client.request_certificate(DomainName=domain, ValidationMethod="DNS")
    arn = cert_response["CertificateArn"]
    return arn


def add_records(client, records, subdom_id, action):
    if records["Type"] == "A":
        response = client.change_resource_record_sets(
            HostedZoneId=subdom_id,
            ChangeBatch={
                "Comment": "Record created for copilot",
                "Changes": [
                    {
                        "Action": action,
                        "ResourceRecordSet": {
                            "Name": records["Name"],
                            "Type": records["Type"],
                            "AliasTarget": {
                                "HostedZoneId": records["AliasTarget"]["HostedZoneId"],
                                "DNSName": records["AliasTarget"]["DNSName"],
                                "EvaluateTargetHealth": records["AliasTarget"][
                                    "EvaluateTargetHealth"
                                ],
                            },
                        },
                    },
                ],
            },
        )
    else:
        response = client.change_resource_record_sets(
            HostedZoneId=subdom_id,
            ChangeBatch={
                "Comment": "Record created for copilot",
                "Changes": [
                    {
                        "Action": action,
                        "ResourceRecordSet": {
                            "Name": records["Name"],
                            "Type": records["Type"],
                            "TTL": records["TTL"],
                            "ResourceRecords": [
                                {"Value": records["ResourceRecords"][0]["Value"]},
                            ],
                        },
                    },
                ],
            },
        )

    check_response(response)
    click.echo(
        click.style(f"{records['Name']}, Type: {records['Type']}", fg="white", bold=True)
        + click.style("Added.", fg="magenta"),
    )
    return response["ChangeInfo"]["Status"]


def check_for_records(client, parent_id, subdom, subdom_id):
    records_to_add = []
    response = client.list_resource_record_sets(
        HostedZoneId=parent_id,
    )

    for records in response["ResourceRecordSets"]:
        if subdom in records["Name"]:
            click.secho(records["Name"] + " found", fg="green")
            records_to_add.append(records)
            add_records(client, records, subdom_id, "UPSERT")
    return True


def create_hosted_zone(client, domain, start_domain, base_len):
    parts = domain.split(".")

    # We only want to create domains max 2 deep so remove all sub domains in excess
    parts_to_remove = len(parts) - base_len - MAX_DOMAIN_DEPTH
    domain_to_create = parts[parts_to_remove:]

    # Walk back domain name
    for x in reversed(range(len(domain_to_create) - (len(start_domain.split(".")) - 1))):
        subdom = ".".join(domain_to_create[(x):]) + "."

        if not click.confirm(
            click.style("About to create domain: ", fg="cyan")
            + click.style(f"{subdom}\n", fg="white", bold=True)
            + click.style("Do you want to continue?", fg="cyan"),
        ):
            exit()

        parent = ".".join(subdom.split(".")[1:])
        response = client.list_hosted_zones_by_name()

        for hz in response["HostedZones"]:
            if hz["Name"] == parent:
                parent_id = hz["Id"]
                break

        click.secho(f"Creating hosted zone for {subdom}...", fg="yellow")
        response = client.create_hosted_zone(
            Name=subdom,
            # Timestamp is on the end because CallerReference must be unique for every call
            CallerReference=f"{subdom}_from_code_{int(time.time())}",
        )
        ns_records = response["DelegationSet"]
        subdom_id = response["HostedZone"]["Id"]

        # Check if records existed in the parent domain, if so they need to be copied to sub domain.
        check_for_records(client, parent_id, subdom, subdom_id)

        if not click.confirm(
            click.style(f"Updating parent {parent} domain with records: ", fg="cyan")
            + click.style(f"{ns_records['NameServers']}\n", fg="white", bold=True)
            + click.style("Do you want to continue?", fg="cyan"),
        ):
            exit()

        # Add NS records of subdomain to parent
        nameservers = ns_records["NameServers"]
        # append  . to make fqdn
        nameservers = [f"{nameserver}." for nameserver in nameservers]
        nameserver_resource_records = [{"Value": nameserver} for nameserver in nameservers]

        client.change_resource_record_sets(
            HostedZoneId=parent_id,
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": subdom,
                            "Type": "NS",
                            "TTL": 300,
                            "ResourceRecords": nameserver_resource_records,
                        },
                    },
                ],
            },
        )

    return True


def check_r53(domain_session, project_session, domain, base_domain):
    # Sanitise base domain
    base_domain = base_domain.rstrip(".") + "."

    # find the hosted zone
    domain_client = domain_session.client("route53")
    acm_client = project_session.client("acm", region_name=AWS_CERT_REGION)

    # create the certificate
    response = domain_client.list_hosted_zones_by_name()
    hosted_zones = {hz["Name"]: hz for hz in response["HostedZones"]}

    abort_if_base_domain_is_not_in_route53(base_domain, hosted_zones)

    base_len = len(base_domain.split(".")) - 1
    parts = domain.split(".")

    for _ in range(len(parts) - 1):
        subdom = ".".join(parts) + "."
        click.secho(f"Searching for {subdom}... ", fg="yellow")
        if subdom in hosted_zones:
            click.secho("Found hosted zone " + hosted_zones[subdom]["Name"], fg="green")

            # We only want to go 2 subdomains deep in Route53
            if (len(parts) - base_len) < MAX_DOMAIN_DEPTH:
                click.secho("Creating Hosted Zone", fg="magenta")
                create_hosted_zone(domain_client, domain, subdom, base_len)

            break

        parts.pop(0)
    else:
        # This should only occur when base domain this needs is not found
        click.secho(f"Root Domain not found for {domain}", fg="red")
        return

    # add records to hosted zone to validate certificate
    cert_arn = create_cert(acm_client, domain_client, domain, base_len)

    return cert_arn


def abort_if_base_domain_is_not_in_route53(base_domain, hosted_zones):
    if base_domain not in hosted_zones:
        click.secho(
            f"The base domain: {base_domain} does not exist in your AWS domain account {hosted_zones}",
            fg="red",
        )
        exit()


def get_load_balancer_domain_and_configuration(
    project_session: Session, app: str, svc: str, env: str
) -> Tuple[str, dict]:
    def separate_hyphenated_application_environment_and_service(
        hyphenated_string, number_of_items_of_interest, number_of_trailing_items
    ):
        # The application name may be hyphenated, so we start splitting
        # at the hyphen after the first item of interest and return the
        # items of interest only...
        return hyphenated_string.rsplit(
            "-", number_of_trailing_items + number_of_items_of_interest - 1
        )[:number_of_items_of_interest]

    proj_client = project_session.client("ecs")

    response = proj_client.list_clusters()
    check_response(response)
    no_items = True
    for cluster_arn in response["clusterArns"]:
        cluster_name = cluster_arn.split("/")[1]
        cluster_app, cluster_env = separate_hyphenated_application_environment_and_service(
            cluster_name, 2, 2
        )
        if cluster_app == app and cluster_env == env:
            no_items = False
            break

    if no_items:
        click.echo(
            click.style("There are no clusters matching ", fg="red")
            + click.style(f"{app} ", fg="white", bold=True)
            + click.style("in this AWS account", fg="red"),
        )
        exit()

    response = proj_client.list_services(cluster=cluster_name)
    check_response(response)
    no_items = True
    for service_arn in response["serviceArns"]:
        fully_qualified_service_name = service_arn.split("/")[2]
        (
            service_app,
            service_env,
            service_name,
        ) = separate_hyphenated_application_environment_and_service(
            fully_qualified_service_name, 3, 2
        )
        if service_app == app and service_env == env and service_name == svc:
            no_items = False
            break

    if no_items:
        click.echo(
            click.style("There are no services matching ", fg="red")
            + click.style(f"{svc}", fg="white", bold=True)
            + click.style(" in this aws account", fg="red"),
        )
        exit()

    elb_client = project_session.client("elbv2")

    elb_arn = elb_client.describe_target_groups(
        TargetGroupArns=[
            proj_client.describe_services(
                cluster=cluster_name,
                services=[
                    fully_qualified_service_name,
                ],
            )["services"][0]["loadBalancers"][0]["targetGroupArn"],
        ],
    )["TargetGroups"][0]["LoadBalancerArns"][0]

    response = elb_client.describe_load_balancers(LoadBalancerArns=[elb_arn])
    check_response(response)

    # Find the domain name
    with open(f"./copilot/{svc}/manifest.yml", "r") as fd:
        conf = yaml.safe_load(fd)
        if "environments" in conf:
            for domain in conf["environments"].items():
                if domain[0] == env:
                    domain_name = domain[1]["http"]["alias"]

        # What happens if domain_name isn't set? Should we raise an error? Return default ? Or None?

    return domain_name, response["LoadBalancers"][0]


@click.group(chain=True, cls=ClickDocOptGroup)
def domain():
    check_copilot_helper_version_needs_update()


@domain.command()
@click.option(
    "--domain-profile",
    help="AWS account profile name for Route53 domains account",
    required=True,
    type=click.Choice(["dev", "live"]),
)
@click.option(
    "--project-profile", help="AWS account profile name for certificates account", required=True
)
@click.option("--base-domain", help="root domain", required=True)
@click.option("--env", help="AWS Copilot environment name", required=False)
def configure(domain_profile, project_profile, base_domain, env):
    """Creates missing subdomains (up to 2 levels deep) if they do not already
    exist and creates certificates for those subdomains."""

    # If you need to reset to debug this command, you will need to delete any of the following
    # which have been created:
    # the certificate in your application's AWS account,
    # the hosted zone for the application environment in the dev AWS account,
    # and the applications records on the hosted zone for the environment in the dev AWS account.

    path = "copilot"

    if not os.path.exists(path):
        abort_with_error("Please check path, copilot directory appears to be missing.")

    manifests = _get_manifests(path)

    if not manifests:
        abort_with_error("Please check path, no manifest files were found")

    domain_session = get_aws_session_or_abort(domain_profile)
    project_session = get_aws_session_or_abort(project_profile)

    cert_list = {}

    for manifest in manifests:
        # Need to check that the manifest file is correctly configured.
        with open(manifest, "r") as fd:
            conf = yaml.safe_load(fd)
            if "environments" in conf:
                click.echo(
                    click.style("Checking file: ", fg="cyan") + click.style(manifest, fg="white"),
                )
                click.secho("Domains listed in manifest file", fg="cyan", underline=True)

                environments = _get_environments(conf, domain_profile, env)

                for env, domain in environments:
                    http_alias = domain["http"]["alias"]
                    click.secho(
                        "\nEnvironment: " + env + " => Domain: " + http_alias,
                        fg="yellow",
                        bold=True,
                    )
                    cert_arn = check_r53(
                        domain_session,
                        project_session,
                        http_alias,
                        base_domain,
                    )
                    cert_list.update({http_alias: cert_arn})

    if cert_list:
        click.secho("\nHere are your Certificate ARNs:", fg="cyan")
        for domain, cert in cert_list.items():
            click.secho(f"Domain: {domain}\t => Cert ARN: {cert}", fg="white", bold=True)
    else:
        click.secho("No domains found, please check the manifest file", fg="red")


def _get_environments(conf, domain_profile, env):
    environments = conf["environments"].items()
    if domain_profile == "live":
        environments = [e for e in environments if e[0] in ["prod", "production"]]
    else:
        environments = [e for e in environments if e[0] not in ["prod", "production"]]
    if env:
        environments = [e for e in environments if e[0] == env]
    return environments


def _get_manifests(path):
    manifests = []
    for root, dirs, files in os.walk(path):
        for file in files:
            if file == "manifest.yml" or file == "manifest.yaml":
                manifests.append(os.path.join(root, file))
    return manifests


@domain.command()
@click.option("--app", help="Application Name", required=True)
@click.option("--env", help="Environment", required=True)
@click.option("--svc", help="Service Name", required=True)
@click.option(
    "--domain-profile",
    help="AWS account profile name for Route53 domains account",
    required=True,
    type=click.Choice(["dev", "live"]),
)
@click.option(
    "--project-profile", help="AWS account profile name for application account", required=True
)
def assign(app, domain_profile, project_profile, svc, env):
    """Assigns the load balancer for a service to its domain name."""
    domain_session = get_aws_session_or_abort(domain_profile)
    project_session = get_aws_session_or_abort(project_profile)

    ensure_cwd_is_repo_root()

    # Find the Load Balancer name.
    domain_name, load_balancer_configuration = get_load_balancer_domain_and_configuration(
        project_session, app, svc, env
    )
    elb_name = load_balancer_configuration["DNSName"]

    click.echo(
        click.style("The Domain: ", fg="yellow")
        + click.style(f"{domain_name}\n", fg="white", bold=True)
        + click.style("has been assigned the Load Balancer: ", fg="yellow")
        + click.style(f"{elb_name}\n", fg="white", bold=True)
        + click.style("Checking to see if this is in Route53", fg="yellow"),
    )

    domain_client = domain_session.client("route53")
    response = domain_client.list_hosted_zones_by_name()
    check_response(response)

    # Scan Route53 Zone for matching domains and update records if needed.
    hosted_zones = {}
    for hz in response["HostedZones"]:
        hosted_zones[hz["Name"]] = hz

    parts = domain_name.split(".")
    for _ in range(len(parts) - 1):
        subdom = ".".join(parts) + "."
        click.echo(
            click.style("Searching for ", fg="yellow")
            + click.style(f"{subdom}..", fg="white", bold=True)
        )

        if subdom in hosted_zones:
            click.echo(
                click.style("Found hosted zone ", fg="yellow")
                + click.style(hosted_zones[subdom]["Name"], fg="white", bold=True),
            )
            hosted_zone_id = hosted_zones[subdom]["Id"]

            # Does record existing
            response = domain_client.list_resource_record_sets(
                HostedZoneId=hosted_zone_id,
            )
            check_response(response)

            for record in response["ResourceRecordSets"]:
                if domain_name == record["Name"][:-1]:
                    click.echo(
                        click.style("Record: ", fg="yellow")
                        + click.style(f"{record['Name']} found", fg="white", bold=True),
                    )
                    click.echo(
                        click.style("is pointing to LB ", fg="yellow")
                        + click.style(
                            f"{record['ResourceRecords'][0]['Value']}", fg="white", bold=True
                        ),
                    )
                    if record["ResourceRecords"][0]["Value"] != elb_name:
                        if click.confirm(
                            click.style("This doesnt match with the current LB ", fg="yellow")
                            + click.style(f"{elb_name}", fg="white", bold=True)
                            + click.style("Do you wish to update the record?", fg="yellow"),
                        ):
                            record = {
                                "Name": domain_name,
                                "Type": "CNAME",
                                "TTL": 300,
                                "ResourceRecords": [{"Value": elb_name}],
                            }
                            add_records(domain_client, record, hosted_zone_id, "UPSERT")
                    else:
                        click.secho("No need to add as it already exists", fg="green")
                    exit()

            record = {
                "Name": domain_name,
                "Type": "CNAME",
                "TTL": 300,
                "ResourceRecords": [{"Value": elb_name}],
            }

            if not click.confirm(
                click.style("Creating Route53 record: ", fg="yellow")
                + click.style(
                    f"{record['Name']} -> {record['ResourceRecords'][0]['Value']}\n",
                    fg="white",
                    bold=True,
                )
                + click.style("In Domain: ", fg="yellow")
                + click.style(f"{subdom}", fg="white", bold=True)
                + click.style("\tZone ID: ", fg="yellow")
                + click.style(f"{hosted_zone_id}\n", fg="white", bold=True)
                + click.style("Do you want to continue?", fg="yellow"),
            ):
                exit()
            add_records(domain_client, record, hosted_zone_id, "CREATE")
            exit()

        parts.pop(0)

    else:
        click.echo(
            click.style("No hosted zone found for ", fg="yellow")
            + click.style(f"{domain_name}", fg="white", bold=True),
        )
        return


if __name__ == "__main__":
    domain()
