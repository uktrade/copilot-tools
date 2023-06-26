from pathlib import Path

TEST_MANIFEST = '# The manifest for the "dev" environment.\n# Read the full specification for the "Environment" type at:\n#  https://aws.github.io/copilot-cli/docs/manifest/environment/\n\n# Your environment name will be used in naming your resources like VPC, cluster, etc.\nname: test\ntype: Environment\n\n# Import your own VPC and subnets or configure how they should be created.\n# network:\n#   vpc:\n#     id:\n\n# Configure the load balancers in your environment, once created.\n\nhttp:\n  public:\n    certificates:\n      - ACM-ARN-FOR-test.landan.cloudapps.digital\n#   private:\n\n\n# Configure observability for your environment resources.\nobservability:\n  container_insights: true\n'
PRODUCTION_MANIFEST = '# The manifest for the "dev" environment.\n# Read the full specification for the "Environment" type at:\n#  https://aws.github.io/copilot-cli/docs/manifest/environment/\n\n# Your environment name will be used in naming your resources like VPC, cluster, etc.\nname: production\ntype: Environment\n\n# Import your own VPC and subnets or configure how they should be created.\n# network:\n#   vpc:\n#     id:\n\n# Configure the load balancers in your environment, once created.\n\nhttp:\n  public:\n    certificates:\n      - ACM-ARN-FOR-test.landan.cloudapps.digital\n#   private:\n\n\n# Configure observability for your environment resources.\nobservability:\n  container_insights: true\n'
SERVICE_MANIFEST = "# The manifest for the \"web\" service.\n# Read the full specification for the \"Load Balanced Web Service\" type at:\n#  https://aws.github.io/copilot-cli/docs/manifest/lb-web-service/\n\n# Your service name will be used in naming your resources like log groups, ECS services, etc.\nname: test-service\ntype: Load Balanced Web Service\n\n# Distribute traffic to your service.\nhttp:\n  # Requests to this path will be forwarded to your service.\n  # To match all requests you can use the \"/\" path.\n  path: '/'\n  # You can specify a custom health check path. The default is \"/\".\n  # healthcheck: '/'\n  target_container: nginx\n  healthcheck:\n    path: '/'\n    port: 8080\n    success_codes: '200,301,302'\n    healthy_threshold: 3\n    unhealthy_threshold: 2\n    interval: 5s\n    timeout: 30s\n    grace_period: 90s\n\nsidecars:\n  nginx:\n    port: 443\n    image: public.ecr.aws/uktrade/nginx-reverse-proxy:latest\n    variables:\n      SERVER: localhost:8000\n      \n\n\n\n  ipfilter:\n    port: 8000\n    image: public.ecr.aws/uktrade/ip-filter:latest\n    variables:\n      PORT: 8000\n      EMAIL_NAME: 'The Department for International Trade WebOps team'\n      EMAIL: test@test.test\n      LOG_LEVEL: DEBUG\n      ORIGIN_HOSTNAME: localhost:8080\n      ORIGIN_PROTO: http\n      CONFIG_FILE: 's3://ipfilter-config/ROUTES.yaml'\n\n\n# Configuration for your containers and service.\nimage:\n\n  location: not-a-url\n    # Port exposed through your container to route traffic to it.\n  port: 8080\n\ncpu: 256       # Number of CPU units for the task.\nmemory: 512 # Amount of memory in MiB used by the task.\ncount: # See https://aws.github.io/copilot-cli/docs/manifest/lb-web-service/#count\n  range: 2-10\n  cooldown:\n    in: 120s\n    out: 60s\n  cpu_percentage: 50\nexec: true     # Enable running commands in your container.\nnetwork:\n  connect: true # Enable Service Connect for intra-environment traffic between services.\n\n# storage:\n  # readonly_fs: true       # Limit to read-only access to mounted root filesystems.\n\n# Optional fields for more advanced use-cases.\n#\nvariables:                    # Pass environment variables as key value pairs.\n  PORT: 8080\n  TEST_VAR:\n  \n\n\n\nsecrets:                      # Pass secrets from AWS Systems Manager (SSM) Parameter Store.\n  TEST_SECRET: /copilot/${COPILOT_APPLICATION_NAME}/${COPILOT_ENVIRONMENT_NAME}/secrets/TEST_SECRET\n  \n\n\n# You can override any of the values defined above by environment.\nenvironments:\n  production:\n    http:\n      alias: test-service.trad.gav.ikx\n  test:\n    http:\n      alias: test-service.landan.cloudapps.digitalx# TODO: enable/disable ip filter on a per env basis.  For example, an service may need an the ip filter in non prod envs, but not prod.\n"
config_file_path = str(Path(__file__).parent.resolve() / "test_config.yml")
INSTRUCTIONS = f"DEPLOYMENT INSTRUCTIONS\n\nProject files have been written to the copilot/ directory.  Any changes to these files should be committed to github.\n\nRun the following commands to bootstrap the app:\n\nNOTES:\n1. you will need to export the AWS_PROFILE env var for the copilot cli tool to pick up:  export AWS_PROFILE=your-aws-profile\n2. Environments will need an ACM TLS certs setting up before they can be deployed.  Speak to SRE for assistance.\n\nYou do not need to follow all of the instructions in sequence. For instance, you may decide to just initialise and deploy one environment, and then deploy a single service into that environment.\n\n# 1. init the app\n\ncopilot app init\n\n# 2. init each service\n\ncopilot svc init --name test-service\n\n# 3. initialise each environment\n\nNOTE: ensure ACM certs have been created and the cert ARNs added to each env's `copilot/environments/{{env}}/manifest.yml' file first.\n\nWhen running \"copilot env init\" chose the following options:\n* Credential source: the correct account that the env should exist in. [NOTE: environments can live in separate accounts.]\n* Default environment configuration? Yes, use default.\n\n\ncopilot env init --name test\ncopilot env init --name production\n\n# 4. deploy each environment\n\ncopilot env deploy --name test\ncopilot env deploy --name production\n\n# 5. migrate the secrets from Gov Paas to AWS/Copilot\n\ncopilot-bootstrap.py migrate-secrets {config_file_path}\n\nYou need to be authenticated via the CF CLI for this command to work.\nUse the --dry-run flag initially to check the output\n\n# 6. deploy each service into each environment\n\n# test-service:\ncopilot svc deploy --name test-service --env test\ncopilot svc deploy --name test-service --env production\n\n\n# 7. Point DNS entries to ALB urls\n\nSpeak to SRE.\n\n# 8. Generate the storage addons\n\nCreate a storage.yml and add the relevant configuration.  See SRE for assistance.\n\nGenerate environment level storage addons\n\ncopilot-bootstrap generate-storage storage.yaml\n\nAdd required secrets to each service's manifest.yml.\n\nRedeploy each environment to provision those secrets\n\n\ncopilot env deploy --name test\ncopilot env deploy --name production\n\n# 9. Switch the bootstrap container to the service container\n\nEdit each copilot/{{service-name}}/manifest.yaml file and replace the image_location with the service's ECR registry url and redeploy.\n\nIt's expected that you'll need to iterate over this step a number of times whilst making changes to the services manifest.yml until the service is stable.\n\n"
