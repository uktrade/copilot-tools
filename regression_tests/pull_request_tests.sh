#!/bin/bash

# exit early if something goes wrong
set -e

echo -e "\nBuild and install platform-helper"
poetry build --no-interaction --format sdist --no-ansi
pip install "dist/$(ls -t1 dist | head -1)"
platform-helper --version

echo -e "\nGet CodeStar connection details"
codestarConnections=$(aws codestar-connections list-connections --provider-type GitHub --query "Connections[? ConnectionStatus == 'AVAILABLE']")
awsAccount=$(echo "$codestarConnections" | jq -r ".[0].OwnerAccountId")
codestarArn=$(echo "$codestarConnections" | jq -r ".[0].ConnectionArn")
codestarConnectionId=$(echo "${codestarArn##*/}")

echo -e "\nClone demodjango_deploy"
git config --global credential.helper '!aws codecommit credential-helper $@'
git config --global credential.UseHttpPath true
git clone "https://codestar-connections.eu-west-2.amazonaws.com/git-http/$awsAccount/eu-west-2/$codestarConnectionId/uktrade/demodjango-deploy.git"

echo -e "\ncd demodjango-deploy"
cd ./demodjango-deploy/

echo -e "\nConfigure AWS Profile"
export AWS_PROFILE="platform-tools"
aws configure --profile "$AWS_PROFILE" set account_id "$AWS_ACCOUNT_ID"
aws configure --profile "$AWS_PROFILE" set region "eu-west-2"
aws configure --profile "$AWS_PROFILE" set output "json"

echo -e "\nRun platform-helper copilot make-addons"
PLATFORM_TOOLS_SKIP_VERSION_CHECK=true platform-helper copilot make-addons

echo -e "\nRun platform-helper check-cloudformation lint"
# see false positive issue https://github.com/aws-cloudformation/cfn-lint/issues/3100
PLATFORM_TOOLS_SKIP_VERSION_CHECK=true platform-helper check-cloudformation lint -i W1011
# echo -e "\nRun platform-helper pipeline generate"
# platform-helper pipeline generate

# echo -e "\nRun copilot env init"
# copilot env init --name toolspr --profile $AWS_PROFILE --default-config

# deploy pipelines

# deploy env (ideally with pipelines)

# deploy services (ideally with pipelines)

# run smoke tests
