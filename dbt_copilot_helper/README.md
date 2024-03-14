# DBT Copilot Tools

## Deprecated

This package has been deprecated. Please switch to using [dbt-platform-helper](https://pypi.org/project/dbt-platform-helper/).

## Introduction

This package contains a set of tools in the form of a Command Line Interface (CLI) primarily for transferring applications/services from [GOV.UK PaaS](https://www.cloud.service.gov.uk) to Department for Business and Trade (DBT) PaaS which augments [AWS Copilot](https://aws.github.io/copilot-cli/). These tools can also be used to provision AWS resources and/or make sure the CloudFormation templates conform to best practices.

## Getting started

To use the Python package `dbt-copilot-tools`, follow the steps below.

### Installation

```shell
pip install dbt-copilot-tools
```

### Usage

Check `dbt-copilot-tools` has installed successfully by executing `copilot-helper` in the terminal emulator. You should see an output similar to the following:

```shell
$ copilot-helper
Usage: copilot-helper [OPTIONS] COMMAND [ARGS]...

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  bootstrap
  check-cloudformation  Runs the checks passed in the command arguments.
  codebuild
  copilot
  domain
```

Each command can be executed without any arguments or additional commands to present the `help` message.

Below is the output for the `bootstrap` command as of version `0.1.2`.

```shell
$ copilot-helper bootstrap --help
Usage: copilot-helper bootstrap [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  instructions     Show migration instructions.
  make-config      Generate copilot boilerplate code.
  migrate-secrets  Migrate secrets from your gov paas application to...
```

See the [Commands Reference](https://github.com/uktrade/copilot-tools/blob/main/dbt_copilot_helper/COMMANDS.md) for a list of all available subcommands.
