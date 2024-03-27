# Commands Reference

- [platform-helper](#platform-helper)
- [platform-helper bootstrap](#platform-helper-bootstrap)
- [platform-helper bootstrap make-config](#platform-helper-bootstrap-make-config)
- [platform-helper bootstrap migrate-secrets](#platform-helper-bootstrap-migrate-secrets)
- [platform-helper bootstrap copy-secrets](#platform-helper-bootstrap-copy-secrets)
- [platform-helper check-cloudformation](#platform-helper-check-cloudformation)
- [platform-helper check-cloudformation lint](#platform-helper-check-cloudformation-lint)
- [platform-helper check-cloudformation check-security](#platform-helper-check-cloudformation-check-security)
- [platform-helper codebase](#platform-helper-codebase)
- [platform-helper codebase prepare](#platform-helper-codebase-prepare)
- [platform-helper codebase list](#platform-helper-codebase-list)
- [platform-helper codebase build](#platform-helper-codebase-build)
- [platform-helper codebase deploy](#platform-helper-codebase-deploy)
- [platform-helper conduit](#platform-helper-conduit)
- [platform-helper config](#platform-helper-config)
- [platform-helper config validate](#platform-helper-config-validate)
- [platform-helper copilot](#platform-helper-copilot)
- [platform-helper copilot make-addons](#platform-helper-copilot-make-addons)
- [platform-helper copilot get-env-secrets](#platform-helper-copilot-get-env-secrets)
- [platform-helper domain](#platform-helper-domain)
- [platform-helper domain configure](#platform-helper-domain-configure)
- [platform-helper domain assign](#platform-helper-domain-assign)
- [platform-helper cdn](#platform-helper-cdn)
- [platform-helper cdn assign](#platform-helper-cdn-assign)
- [platform-helper cdn delete](#platform-helper-cdn-delete)
- [platform-helper cdn list](#platform-helper-cdn-list)
- [platform-helper environment](#platform-helper-environment)
- [platform-helper environment offline](#platform-helper-environment-offline)
- [platform-helper environment online](#platform-helper-environment-online)
- [platform-helper generate](#platform-helper-generate)
- [platform-helper pipeline](#platform-helper-pipeline)
- [platform-helper pipeline generate](#platform-helper-pipeline-generate)
- [platform-helper application](#platform-helper-application)
- [platform-helper application container-stats](#platform-helper-application-container-stats)
- [platform-helper application task-stats](#platform-helper-application-task-stats)

# platform-helper

## Usage

```
platform-helper <command> [--version] 
```

## Options

- `--version <boolean>` _Defaults to False._
  - Show the version and exit.
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`application` ↪](#platform-helper-application)
- [`bootstrap` ↪](#platform-helper-bootstrap)
- [`cdn` ↪](#platform-helper-cdn)
- [`check-cloudformation` ↪](#platform-helper-check-cloudformation)
- [`codebase` ↪](#platform-helper-codebase)
- [`conduit` ↪](#platform-helper-conduit)
- [`config` ↪](#platform-helper-config)
- [`copilot` ↪](#platform-helper-copilot)
- [`domain` ↪](#platform-helper-domain)
- [`environment` ↪](#platform-helper-environment)
- [`generate` ↪](#platform-helper-generate)
- [`pipeline` ↪](#platform-helper-pipeline)

# platform-helper bootstrap

[↩ Parent](#platform-helper)

## Usage

```
platform-helper bootstrap (make-config|migrate-secrets|copy-secrets) 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`copy-secrets` ↪](#platform-helper-bootstrap-copy-secrets)
- [`make-config` ↪](#platform-helper-bootstrap-make-config)
- [`migrate-secrets` ↪](#platform-helper-bootstrap-migrate-secrets)

# platform-helper bootstrap make-config

[↩ Parent](#platform-helper-bootstrap)

    Generate Copilot boilerplate code.

## Usage

```
platform-helper bootstrap make-config [-d <directory>] 
```

## Options

- `-d
--directory <text>` _Defaults to .._

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper bootstrap migrate-secrets

[↩ Parent](#platform-helper-bootstrap)

    Migrate secrets from your GOV.UK PaaS application to DBT PaaS.

    You need to be authenticated via Cloud Foundry CLI and the AWS CLI to use this command.

    If you're using AWS profiles, use the AWS_PROFILE environment variable to indicate the which
    profile to use, e.g.:

    AWS_PROFILE=myaccount copilot-bootstrap.py ...

## Usage

```
platform-helper bootstrap migrate-secrets --project-profile <project_profile> 
                                          --env <environment> [--svc <service>] 
                                          [--overwrite] [--dry-run] 
```

## Options

- `--project-profile <text>`
  - AWS account profile name
- `--env <text>`
  - Migrate secrets from a specific environment
- `--svc <text>`
  - Migrate secrets from a specific service
- `--overwrite <boolean>` _Defaults to False._
  - Overwrite existing secrets?
- `--dry-run <boolean>` _Defaults to False._
  - dry run
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper bootstrap copy-secrets

[↩ Parent](#platform-helper-bootstrap)

    Copy secrets from one environment to a new environment.

## Usage

```
platform-helper bootstrap copy-secrets <source_environment> <target_environment> 
                                       --project-profile <project_profile> 
```

## Arguments

- `source_environment <text>`
- `target_environment <text>`

## Options

- `--project-profile <text>`
  - AWS account profile name
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper check-cloudformation

[↩ Parent](#platform-helper)

    Runs the checks passed in the command arguments.

    If no argument is passed, it will run all the checks.

## Usage

```
platform-helper check-cloudformation (lint|check-security) 
                                     [-d <directory>] 
```

## Options

- `-d
--directory <text>` _Defaults to copilot._

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`check-security` ↪](#platform-helper-check-cloudformation-check-security)
- [`lint` ↪](#platform-helper-check-cloudformation-lint)

# platform-helper check-cloudformation lint

[↩ Parent](#platform-helper-check-cloudformation)

    Runs cfn-lint against the generated CloudFormation templates.

## Usage

```
platform-helper check-cloudformation lint [-d <directory>] [-i <ignore_checks>] 
```

## Options

- `-d
--directory <text>` _Defaults to copilot._

- `-i
--ignore-checks <text>` _Defaults to []._

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper check-cloudformation check-security

[↩ Parent](#platform-helper-check-cloudformation)

## Usage

```
platform-helper check-cloudformation check-security [-d <directory>] 
```

## Options

- `-d
--directory <text>` _Defaults to copilot._

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper codebase

[↩ Parent](#platform-helper)

    Codebase commands.

## Usage

```
platform-helper codebase (prepare|list|build|deploy) 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`build` ↪](#platform-helper-codebase-build)
- [`deploy` ↪](#platform-helper-codebase-deploy)
- [`list` ↪](#platform-helper-codebase-list)
- [`prepare` ↪](#platform-helper-codebase-prepare)

# platform-helper codebase prepare

[↩ Parent](#platform-helper-codebase)

    Sets up an application codebase for use within a DBT platform project.

## Usage

```
platform-helper codebase prepare 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper codebase list

[↩ Parent](#platform-helper-codebase)

    List available codebases for the application.

## Usage

```
platform-helper codebase list --app <application> [--with-images] 
```

## Options

- `--app <text>`
  - AWS application name
- `--with-images <boolean>` _Defaults to False._
  - List up to the last 10 images tagged for this codebase
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper codebase build

[↩ Parent](#platform-helper-codebase)

    Trigger a CodePipeline pipeline based build.

## Usage

```
platform-helper codebase build --app <application> --codebase <codebase> 
                               --commit <commit> 
```

## Options

- `--app <text>`
  - AWS application name
- `--codebase <text>`
  - The codebase name as specified in the pipelines.yml file
- `--commit <text>`
  - GitHub commit hash
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper codebase deploy

[↩ Parent](#platform-helper-codebase)

    Trigger a CodePipeline pipeline based deployment.

## Usage

```
platform-helper codebase deploy --app <application> --env <environment> --codebase <codebase> 
                                --commit <commit> 
```

## Options

- `--app <text>`
  - AWS application name
- `--env <text>`
  - AWS Copilot environment
- `--codebase <text>`
  - The codebase name as specified in the pipelines.yml file
- `--commit <text>`
  - GitHub commit hash
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper conduit

[↩ Parent](#platform-helper)

    Create a conduit connection to an addon.

## Usage

```
platform-helper conduit <addon_name> 
                        --app <application> --env <environment> [--access (read|write|admin)] 
```

## Arguments

- `addon_name <text>`

## Options

- `--app <text>`
  - AWS application name
- `--env <text>`
  - AWS environment name
- `--access <choice>` _Defaults to read._
  - Allow write or admin access to database addons
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper config

[↩ Parent](#platform-helper)

    Perform actions on configuration files.

## Usage

```
platform-helper config validate 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`validate` ↪](#platform-helper-config-validate)

# platform-helper config validate

[↩ Parent](#platform-helper-config)

    Validate deployment or application configuration.

## Usage

```
platform-helper config validate 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper copilot

[↩ Parent](#platform-helper)

## Usage

```
platform-helper copilot (make-addons|get-env-secrets) 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`get-env-secrets` ↪](#platform-helper-copilot-get-env-secrets)
- [`make-addons` ↪](#platform-helper-copilot-make-addons)

# platform-helper copilot make-addons

[↩ Parent](#platform-helper-copilot)

    Generate addons CloudFormation for each environment.

## Usage

```
platform-helper copilot make-addons 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper copilot get-env-secrets

[↩ Parent](#platform-helper-copilot)

    List secret names and values for an environment.

## Usage

```
platform-helper copilot get-env-secrets <application> <environment> 
```

## Arguments

- `app <text>`
- `env <text>`

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper domain

[↩ Parent](#platform-helper)

## Usage

```
platform-helper domain (configure|assign) 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`assign` ↪](#platform-helper-domain-assign)
- [`configure` ↪](#platform-helper-domain-configure)

# platform-helper domain configure

[↩ Parent](#platform-helper-domain)

    Creates subdomains if they do not exist and then creates certificates for
    them.

## Usage

```
platform-helper domain configure --project-profile <project_profile> 
                                 --env <environment> 
```

## Options

- `--project-profile <text>`
  - AWS account profile name for certificates account
- `--env <text>`
  - AWS Copilot environment name
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper domain assign

[↩ Parent](#platform-helper-domain)

    Assigns the load balancer for a service to its domain name.

## Usage

```
platform-helper domain assign --app <application> --env <environment> --svc <service> 
                              --domain-profile (dev|live) --project-profile <project_profile> 
```

## Options

- `--app <text>`
  - Application Name
- `--env <text>`
  - Environment
- `--svc <text>`
  - Service Name
- `--domain-profile <choice>`
  - AWS account profile name for Route53 domains account
- `--project-profile <text>`
  - AWS account profile name for application account
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper cdn

[↩ Parent](#platform-helper)

## Usage

```
platform-helper cdn (assign|delete|list) 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`assign` ↪](#platform-helper-cdn-assign)
- [`delete` ↪](#platform-helper-cdn-delete)
- [`list` ↪](#platform-helper-cdn-list)

# platform-helper cdn assign

[↩ Parent](#platform-helper-cdn)

    Assigns a CDN domain name to application loadbalancer.

## Usage

```
platform-helper cdn assign --project-profile <project_profile> --env <environment> 
                           --app <application> --svc <service> 
```

## Options

- `--project-profile <text>`
  - AWS account profile name for certificates account
- `--env <text>`
  - AWS Copilot environment name
- `--app <text>`
  - Application Name
- `--svc <text>`
  - Service Name
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper cdn delete

[↩ Parent](#platform-helper-cdn)

    Assigns a CDN domain name to application loadbalancer.

## Usage

```
platform-helper cdn delete --project-profile <project_profile> --env <environment> 
                           --app <application> --svc <service> 
```

## Options

- `--project-profile <text>`
  - AWS account profile name for certificates account
- `--env <text>`
  - AWS Copilot environment name
- `--app <text>`
  - Application Name
- `--svc <text>`
  - Service Name
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper cdn list

[↩ Parent](#platform-helper-cdn)

    List CDN domain name attached to application loadbalancer.

## Usage

```
platform-helper cdn list --project-profile <project_profile> --env <environment> 
                         --app <application> --svc <service> 
```

## Options

- `--project-profile <text>`
  - AWS account profile name for certificates account
- `--env <text>`
  - AWS Copilot environment name
- `--app <text>`
  - Application Name
- `--svc <text>`
  - Service Name
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper environment

[↩ Parent](#platform-helper)

    Commands affecting environments.

## Usage

```
platform-helper environment (offline|online) 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`offline` ↪](#platform-helper-environment-offline)
- [`online` ↪](#platform-helper-environment-online)

# platform-helper environment offline

[↩ Parent](#platform-helper-environment)

    Take load-balanced web services offline with a maintenance page.

## Usage

```
platform-helper environment offline --app <application> --env <environment> [--template (default|migration)] 
```

## Options

- `--app <text>`

- `--env <text>`

- `--template <choice>` _Defaults to default._
  - The maintenance page you wish to put up.
- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper environment online

[↩ Parent](#platform-helper-environment)

    Remove a maintenance page from an environment.

## Usage

```
platform-helper environment online --app <application> --env <environment> 
```

## Options

- `--app <text>`

- `--env <text>`

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper generate

[↩ Parent](#platform-helper)

    Generate deployment pipeline configuration files and generate addons
    CloudFormation template files for each environment.

    Wraps pipeline generate and make-addons.

## Usage

```
platform-helper generate 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper pipeline

[↩ Parent](#platform-helper)

    Pipeline commands.

## Usage

```
platform-helper pipeline generate 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`generate` ↪](#platform-helper-pipeline-generate)

# platform-helper pipeline generate

[↩ Parent](#platform-helper-pipeline)

    WARNING: this command should not be used as a stand-alone.
    Use `platform-helper generate` instead.

    Given a pipelines.yml file, generate environment and service deployment
    pipelines.

## Usage

```
platform-helper pipeline generate 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper application

[↩ Parent](#platform-helper)

    Application metrics.

## Usage

```
platform-helper application (container-stats|task-stats) 
```

## Options

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

## Commands

- [`container-stats` ↪](#platform-helper-application-container-stats)
- [`task-stats` ↪](#platform-helper-application-task-stats)

# platform-helper application container-stats

[↩ Parent](#platform-helper-application)

    Command to get application container level metrics.

## Usage

```
platform-helper application container-stats --env <environment> --app <application> 
                                            [--storage] [--network] 
```

## Options

- `--env <text>`

- `--app <text>`

- `--storage <boolean>` _Defaults to False._

- `--network <boolean>` _Defaults to False._

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.

# platform-helper application task-stats

[↩ Parent](#platform-helper-application)

    Command to get application task level metrics.

## Usage

```
platform-helper application task-stats --env <environment> --app <application> [--disk] 
                                       [--storage] [--network] 
```

## Options

- `--env <text>`

- `--app <text>`

- `--disk <boolean>` _Defaults to False._

- `--storage <boolean>` _Defaults to False._

- `--network <boolean>` _Defaults to False._

- `--help <boolean>` _Defaults to False._
  - Show this message and exit.
