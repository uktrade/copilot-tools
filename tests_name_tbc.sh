#!/bin/bash

# exit early if something goes wrong
set -e


echo "Build and install copilot-helper"
poetry build --no-interaction --format sdist --no-ansi
pip install "dist/$(ls -t1 dist | head -1)"
copilot-helper --version

echo "Get CodeStar connection details"
codestarConnections=$(aws codestar-connections list-connections --provider-type GitHub --query "Connections[? ConnectionStatus == 'AVAILABLE']")
awsAccount=$(echo "$codestarConnections" | jq -r ".[0].OwnerAccountId")
codestarArn=$(echo "$codestarConnections" | jq -r ".[0].ConnectionArn")
codestarConnectionId=$(echo "${codestarArn##*/}")

echo "Clone demodjango_deploy"
git config --global credential.helper '!aws codecommit credential-helper $@'
git config --global credential.UseHttpPath true
git clone "https://codestar-connections.eu-west-2.amazonaws.com/git-http/$awsAccount/eu-west-2/$codestarConnectionId/uktrade/demodjango-deploy.git"

# change working directory
echo "cd demodjango-deploy"
cd ./demodjango-deploy/

# make-addons
echo "Run make-addons from copilot-helper"
export AWS_PROFILE="platform-sandbox"
aws configure --profile "$AWS_PROFILE" set account_id "$PLATFORM_SANDBOX_ACCOUNT_ID"
aws configure --profile "$AWS_PROFILE" set region "eu-west-2"
aws configure --profile "$AWS_PROFILE" set output "json"

# TODO: copilot-tools is set to 1.0.2 should be 1.1.2 / skipped / disable version check

copilot-helper copilot make-addons
ls ./copilot/environments/addons

# deploy env

# deploy services

# run smoke tests
