#!/usr/bin/env python

import pprint
import click
import boto3
import json
import os
import yaml
import time

from schema import Optional, Schema, SchemaError


# To do
# -----
# Need to change this to a class to make it more cleaner
# Need to seperate Dev and Prod in this app - related to prod domain not being found if specified dev profile for the domain
# Check user has logged into the aws accounts before scanning the accounts
# Change script to list all the domains and certs its going to create.  Let the user select
# Need to check that the manifest.yml file is correctly configured.
# When adding records from parent to subdomain, if ok, it then should remove them from parent domain (run a test before removing)
# For each domain in manifest.yml:
# Cert issued?  - No, do you want to create it?
# Cert validated? - No, do you want to validate it?
# Hosted zone exists? No, exit, user needs to rectify
# Domain is either:
#     - Mapped to some thing else - Yes, exit, user needs to rectify
#     - Is available but unmapped - No, do you want to point DNS at ALB?
#     - Is already mapped to the ALB - OK, everything is sweet


MAX_DOMAIN_DEPTH = 2
AWS_CERT_REGION = "eu-west-2"


def wait_for_certificate_validation(acm_client, certificate_arn, sleep_time=5, timeout=600):

    print("waiting for cert...")
    status = acm_client.describe_certificate(CertificateArn=certificate_arn)['Certificate']['Status']
    elapsed_time = 0
    while status == 'PENDING_VALIDATION':
        if elapsed_time > timeout:
            raise Exception(f'Timeout ({timeout}s) reached for certificate validation')
        print(f"{certificate_arn}: Waiting {sleep_time}s for validation, {elapsed_time}s elapsed...")
        time.sleep(sleep_time)
        status = acm_client.describe_certificate(CertificateArn=certificate_arn)['Certificate']['Status']
        elapsed_time += sleep_time
    print("cert validated...")


def create_cert(client, domain_client, domain, base_domain):
    #breakpoint()
    # Check if cert is present.
    arn = ""
    resp = client.list_certificates(
            CertificateStatuses=[
                'PENDING_VALIDATION', 'ISSUED', 'INACTIVE', 'EXPIRED', 'VALIDATION_TIMED_OUT', 'REVOKED', 'FAILED'
            ],
            MaxItems=500)
    #Need to check if cert status is issued, if pending need to update dns

    for cert in resp["CertificateSummaryList"]:
        if domain  == cert['DomainName']:
            print("Cert already exists, do not need to create")
            #breakpoint()
            return cert['CertificateArn']

    if not click.confirm(f"Creating Cert for {domain}\nDo you want to continue?"):
        exit()

    parts = domain.split(".")

    # We only want to create domains max 2 deep so remove all sub domains in excess
    parts_to_remove = len(parts) - len(base_domain.split(".")) - MAX_DOMAIN_DEPTH
    domain_to_create = ".".join(parts[parts_to_remove:]) + "."
    print(domain_to_create)
    #breakpoint()
    #cert_client = DNSValidatedACMCertClient(domain=domain, profile='intranet')
    response = client.request_certificate(
        DomainName=domain, ValidationMethod='DNS')

    arn = response['CertificateArn']
    # Create DNS validation records

    # Need a pause for it to populate the DNS resource records


    response = client.describe_certificate(
        CertificateArn=arn
    )
    #print(response)
    #breakpoint()
    while response['Certificate'].get('DomainValidationOptions') is None or response['Certificate']['DomainValidationOptions'][0].get('ResourceRecord') is None:
        print("Waiting for DNS records...")
        time.sleep(2)
        response = client.describe_certificate(
            CertificateArn=arn
        )

    cert_record = response['Certificate']['DomainValidationOptions'][0]['ResourceRecord']


    response = domain_client.list_hosted_zones_by_name()

    for hz in response["HostedZones"]:
        if  hz['Name'] == domain_to_create:
            #breakpoint()
            domain_id = hz['Id']
            break
    #breakpoint()
    # Add NS records of subdomain to parent
    print(domain_id)

    if not click.confirm(f"Updating DNS record for cert {domain}\nDo you want to continue?"):
        exit()

    response = domain_client.change_resource_record_sets(
        HostedZoneId=domain_id,
        ChangeBatch={
            'Changes': [{
                'Action': 'CREATE',
                'ResourceRecordSet': {
                    'Name': cert_record['Name'],
                    'Type': cert_record['Type'],
                    'TTL': 300,
                    'ResourceRecords': [{'Value': cert_record['Value']},],
                }
            }]
        }
    )

    #print(response)

    # Wait for certificate to get to validation state before continuing
    wait_for_certificate_validation(client, certificate_arn=arn, sleep_time=5, timeout=600)

    return arn


def add_records(client, records, subdom_id):
    # breakpoint()
    if records['Type'] == "A":
        response = client.change_resource_record_sets(
            HostedZoneId=subdom_id,
            ChangeBatch={
                'Changes': [{
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'Name': records['Name'],
                        'Type': records['Type'],
                        'AliasTarget': {
                            'HostedZoneId': records['AliasTarget']['HostedZoneId'],
                            'DNSName': records['AliasTarget']['DNSName'],
                            'EvaluateTargetHealth': records['AliasTarget']['EvaluateTargetHealth']
                        },
                    }
                }]
            }
        )
    else:
        response = client.change_resource_record_sets(
            HostedZoneId=subdom_id,
            ChangeBatch={
                'Changes': [{
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'Name': records['Name'],
                        'Type': records['Type'],
                        'TTL': records['TTL'],
                        'ResourceRecords': [{'Value': records['ResourceRecords'][0]['Value']},],
                    }
                }]
            }
        )

    print(f"{records['Name']}, Type: {records['Type']} Added.")


def check_for_records(client, domain, parent_id, subdom, subdom_id):

    records_to_add = []
    print(parent_id)

    response = client.list_resource_record_sets(
        HostedZoneId=parent_id,
    )
    print(response)
    for records in response['ResourceRecordSets']:
        #print(records['name'])
        if subdom in records['Name']:
            #breakpoint()
            print(records['Name'], " found")
            records_to_add.append(records)
            add_records(client, records, subdom_id)

    #breakpoint()
    #print("Records added: ", records_to_add)


    return



def create_hosted_zone(client, domain, start_domain, base_domain):
    print("Creating new Zone")

    parts = domain.split(".")

    # We only want to create domains max 2 deep so remove all sub domains in excess
    parts_to_remove = len(parts) - len(base_domain.split(".")) - MAX_DOMAIN_DEPTH
    domain_to_create = parts[parts_to_remove:]
    #print(domain_to_create)

    #breakpoint()
    # Walk back domain name
    for x in reversed(range(len(domain_to_create) - (len(start_domain.split(".")) - 1))):
        subdom = ".".join(domain_to_create[(x):]) + "."

        if not click.confirm(f"Do you wish to create domain {subdom}...\nDo you want to continue?"):
            exit()

        parent = ".".join(subdom.split(".")[1:])
        response = client.list_hosted_zones_by_name()

        for hz in response["HostedZones"]:
            if  hz['Name'] == parent:
                #breakpoint()
                parent_id = hz['Id']
                break



        # update CallerReference to unique string eg date.
        #breakpoint()
        response = client.create_hosted_zone(
            Name=subdom,
            CallerReference=f'{subdom}_from_code',
        )
        ns_records = response['DelegationSet']
        subdom_id = response['HostedZone']['Id']

        # Check if records existed in the domain, if so they need to be copied to sub domain.
        check_for_records(client, domain, parent_id, subdom, subdom_id)


        if not click.confirm(f"Updating parent {parent} domain with records {ns_records['NameServers']}\nDo you want to continue?"):
            exit()


        # Add NS records of subdomain to parent
        #print(parent_id)

        nameservers = ns_records['NameServers']
        # append  . to make fqdn
        nameservers = ['{}.'.format(nameserver) for nameserver in nameservers]
        # Convert into Dict
        nameserver_resource_records = [{'Value': nameserver} for nameserver in nameservers]
        # breakpoint()
        response = client.change_resource_record_sets(
            HostedZoneId=parent_id,
            ChangeBatch={
                'Changes': [{
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'Name': subdom,
                        'Type': 'NS',
                        'TTL': 300,
                        'ResourceRecords': nameserver_resource_records,
                    }
                }]
            }
        )

        print(response)



def check_r53(domain_profile, project_profile, domain, base_domain):
    # route 53 / ACM POC
    pp = pprint.PrettyPrinter(depth=6)


    PROJECT_ACC_PROFILE = project_profile
    DOMAIN_ACC_PROFILE = domain_profile

    project_session = boto3.session.Session(profile_name=PROJECT_ACC_PROFILE)
    domain_session = boto3.session.Session(profile_name=DOMAIN_ACC_PROFILE)

    # find the hosted zone
    domain_client = domain_session.client('route53')
    acm_client = project_session.client('acm', region_name=AWS_CERT_REGION)

    sts_dom = domain_session.client('sts')
    alias_client = domain_session.client('iam')
    account_name = alias_client.list_account_aliases()['AccountAliases']
    print(f"Logged in with AWS Domain account: {account_name[0]}/{sts_dom.get_caller_identity()['Account']}\nUser: {sts_dom.get_caller_identity()['UserId']}")
    alias_client = project_session.client('iam')
    account_name = alias_client.list_account_aliases()['AccountAliases']
    sts_proj = project_session.client('sts')
    print(f"Logged in with AWS Project account: {account_name[0]}/{sts_proj.get_caller_identity()['Account']}\nUser: {sts_proj.get_caller_identity()['UserId']}")
    #breakpoint()
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/acm.html
    # create the certificate

    #breakpoint()
    response = domain_client.list_hosted_zones_by_name()

    # check if prod, feature not implemented yet.
    LIVE = False
    hosted_zones = {}
    for hz in response["HostedZones"]:
        hosted_zones[hz["Name"]] = hz

    base_len = len(base_domain.split("."))
    #breakpoint()

    parts = domain.split(".")


    for _ in range(len(parts) - 1):
        subdom = ".".join(parts) + "."
        print(f"searching for {subdom}... ")
        if subdom in hosted_zones:
            #breakpoint()
            print("Found hosted zone", hosted_zones[subdom]['Name'])

            hosted_zone_id = hosted_zones[subdom]["Id"]
            hosted_zone_conf = hosted_zones[subdom]
            #zone_to_create = subdom

            # We only want to go 2 sub domains deep in R53
            if (len(parts) - base_len) < MAX_DOMAIN_DEPTH:
                create_hosted_zone(domain_client, domain, subdom, base_domain)

            break

        parts.pop(0)
    else:
        print(f"No hosted zone found for {domain}")
        return
        #This should only occur when base domain is not found or is in the wrong account
        #Need to figure this out
        #create_hosted_zone(domain_client, domain, subdom, base_domain)

    # get hosted zone
    #breakpoint()
    response = domain_client.get_hosted_zone(
        Id=hosted_zone_id
    )

    response = domain_client.list_resource_record_sets(
        HostedZoneId=hosted_zone_id
    )

    cert_arn = create_cert(acm_client, domain_client, domain, base_domain)
    # breakpoint()
    # pp.pprint(response)

    # add records to hosted zone to validate certificate

    return cert_arn


@click.group()
def cli():
    pass


@cli.command()
@click.option('--update', is_flag=True, show_default=True, default=False, help='Update config')
@click.option('--path', help='path of copilot folder')
@click.option('--domain-profile', help='aws account profile name for R53 domains account')
@click.option('--project-profile', help='aws account profile name for certificates account')
@click.option('--base-domain', help='root domain')
@click.option('--desc', help='Description of project')
def check_domain(update, path, domain_profile, project_profile, base_domain, desc):
    """
    Scans to see if Domain exists
    """


    cert_list = {}

    for root, dirs, files in os.walk(path):
        for file in files:
            if file == "manifest.yml":

                 #Need to check that the manifest file is correctly configured.

                 with open(os.path.join(root, file), "r") as fd:
                     #breakpoint()
                     conf = yaml.safe_load(fd)
                     if 'environments' in conf:
                         print("Checking file:")
                         print(os.path.join(root, file))
                         print("Domains listed in Manifest")

                         for env, domain in conf['environments'].items():
                             print("Env: ", env, " - Domain", domain['http']['alias'])
                             cert_arn = check_r53(domain_profile, project_profile, domain['http']['alias'], base_domain)

                             cert_list.update({domain['http']['alias']: cert_arn})

    print("\nHere are your Cert ARNs\n")
    #breakpoint()
    for domain, cert in cert_list.items():
        print(f"Domain: {domain}\t - Cert ARN: {cert}")


if __name__ == "__main__":
    cli()
