import * as path from 'path';
import {readFileSync} from "fs";
import {execSync} from "child_process";

import {parse, stringify} from 'yaml';
import * as cdk from 'aws-cdk-lib';

import {
    CodeStarConnectionListConnectionsOutput,
    PipelineManifest,
    PipelinesConfiguration,
    TransformedStackProps
} from "./types";

export class TransformedStack extends cdk.Stack {
    public readonly template: cdk.cloudformation_include.CfnInclude;
    public readonly appName: string;
    private pipelineManifest: PipelineManifest;
    private codestarConnection: { arn: string; id: string; };
    private deployRepository: string;
    private codebaseConfiguration: PipelinesConfiguration['codebases'][0];

    constructor(scope: cdk.App, id: string, props: TransformedStackProps) {
        super(scope, id, props);
        this.template = new cdk.cloudformation_include.CfnInclude(this, 'Template', {
            templateFile: path.join('.build', 'in.yml'),
        });
        this.appName = props.appName;

        // Load external configuration
        this.loadManifestFiles();
        this.loadCodestarConnection();
        this.loadGitRemote();

        // Alter cloudformation template
        this.createImageBuildProject();
        this.createECRRepository();
        this.updatePipelineBuildProject();
        this.updatePipelines();
        this.allowBuildProjectToUseCodestarConnection();
        this.allowPipelineToDescribeECRImages();
    }

    private createImageBuildProject() {
        const filterGroups: Array<Array<{ type: string, pattern: string; }>> = [];
        const watchedBranches = new Set(
            this.codebaseConfiguration.pipelines.map(p => p.branch)
                .filter(p => !!p),
        );

        for (const branch of watchedBranches) {
            filterGroups.push([
                {type: 'EVENT', pattern: 'PUSH'},
                {type: 'HEAD_REF', pattern: `^refs/heads/${branch}$`},
            ]);
        }

        if (this.codebaseConfiguration.pipelines.some(p => p.tag)) {
            filterGroups.push([
                {type: 'EVENT', pattern: 'PUSH'},
                {type: 'HEAD_REF', pattern: '^refs/tags/.*'},
            ]);
        }

        new cdk.aws_codebuild.CfnProject(this, 'ImageBuildProject', {
            name: `codebuild-${this.appName}-${this.pipelineManifest.name}`,
            description: `Publish images on push to ${this.codebaseConfiguration.repository}`,
            badgeEnabled: true,
            encryptionKey: cdk.Fn.importValue(`${this.appName}-ArtifactKey`),
            serviceRole: this.template.getResource('BuildProjectRole').getAtt('Arn').toString(),
            timeoutInMinutes: 30,
            visibility: 'PRIVATE',
            artifacts: {
                type: 'NO_ARTIFACTS',
            },
            cache: {
                modes: ['LOCAL_DOCKER_LAYER_CACHE'],
                type: 'LOCAL',
            },
            triggers: {
                buildType: 'BUILD',
                filterGroups,
                webhook: true,
            },
            environment: {
                type: 'LINUX_CONTAINER',
                computeType: 'BUILD_GENERAL1_SMALL',
                privilegedMode: true,
                image: 'public.ecr.aws/uktrade/ci-image-builder',
                environmentVariables: [
                    {name: 'AWS_ACCOUNT_ID', value: this.account},
                ],
            },
            source: {
                type: 'GITHUB',
                location: `https://github.com/${this.codebaseConfiguration.repository}.git`,
                gitCloneDepth: 0,
                auth: {type: 'OAUTH'},
                gitSubmodulesConfig: {fetchSubmodules: true},
                buildSpec: stringify(parse(
                    readFileSync(path.join(__dirname, 'buildspec.image.yml')).toString('utf-8'),
                )),
            },
        });
    }

    private createECRRepository() {
        new cdk.aws_ecr.CfnRepository(this, 'ECRRepository', {
            repositoryName: `${this.appName}/${this.codebaseConfiguration.name}`,
            imageTagMutability: 'MUTABLE',
            imageScanningConfiguration: {
                scanOnPush: true,
            },
            lifecyclePolicy: {
                lifecyclePolicyText: JSON.stringify({
                    rules: [
                        {
                            rulePriority: 1,
                            description: "Delete untagged images after 7 days",
                            selection: {
                                tagStatus: "untagged",
                                countType: "sinceImagePushed",
                                countUnit: "days",
                                countNumber: 7,
                            },
                            action: {
                                type: "expire"
                            },
                        },
                    ],
                }),
            },
        });
    }

    private updatePipelineBuildProject() {
        const buildProject = this.template.getResource("BuildProject") as cdk.aws_codebuild.CfnProject;

        const currentEnvironment = buildProject.environment as cdk.aws_codebuild.CfnProject.EnvironmentProperty;
        const currentEnvironmentVariables = currentEnvironment.environmentVariables as Array<cdk.aws_codebuild.CfnProject.EnvironmentVariableProperty>;

        buildProject.environment = {
            ...buildProject.environment,
            image: 'public.ecr.aws/uktrade/ci-image-builder',
            environmentVariables: [
                ...currentEnvironmentVariables,
                {
                    name: 'CODESTAR_CONNECTION_ID',
                    value: this.codestarConnection.id
                },
                {
                    name: 'DEPLOY_REPOSITORY',
                    value: this.deployRepository
                },
                {
                    name: 'CODEBASE_REPOSITORY',
                    value: this.codebaseConfiguration.repository
                },
                {
                    name: 'COPILOT_SERVICES',
                    value: this.codebaseConfiguration.services.join(' ')
                },
                {
                    name: 'ECR_REPOSITORY',
                    value: cdk.Fn.ref('ECRRepository')
                }
            ]
        } as cdk.aws_codebuild.CfnProject.EnvironmentProperty;

        const currentSource = buildProject.source as cdk.aws_codebuild.CfnProject.SourceProperty;

        buildProject.source = {
            ...currentSource,
            buildSpec: stringify(parse(
                readFileSync(path.join(__dirname, 'buildspec.deploy.yml')).toString('utf-8'),
            )),
        };
    }

    private updatePipelines() {
        const existingPipeline = this.template.getResource("Pipeline") as cdk.aws_codepipeline.CfnPipeline;

        // Here we co-opt the existing pipeline resource to alter covering our first pipeline.
        const [firstPipelineConfiguration] = this.codebaseConfiguration.pipelines.splice(0, 1);
        this.updateExistingPipeline(existingPipeline, firstPipelineConfiguration);

        for (const [index, pipelineConfiguration] of this.codebaseConfiguration.pipelines.entries()) {
            this.createPipeline(index, pipelineConfiguration, existingPipeline);
        }
    }

    private createPipeline(index: number, pipelineConfig: PipelinesConfiguration['codebases'][0]['pipelines'][0], existingPipeline: cdk.aws_codepipeline.CfnPipeline) {
        const pipeline = new cdk.aws_codepipeline.CfnPipeline(this, `Pipeline${index + 1}`, {
            name: `pipeline-${this.appName}-${this.codebaseConfiguration.name}-${pipelineConfig.name}`,
            roleArn: cdk.Fn.getAtt('PipelineRole', 'Arn').toString(),
            artifactStores: existingPipeline.artifactStores,
            stages: [
                {
                    name: "Source",
                    actions: [
                        {
                            name: 'ImagePublished',
                            runOrder: 1,
                            configuration: {
                                RepositoryName: cdk.Fn.ref('ECRRepository'),
                                ImageTag: pipelineConfig.tag ? 'tag-latest' : `branch-${pipelineConfig.branch}`,
                            },
                            outputArtifacts: [{name: 'ECRMetadata'}],
                            actionTypeId: {
                                category: 'Source',
                                owner: 'AWS',
                                version: '1',
                                provider: 'ECR',
                            },
                        },
                    ],
                },
            ],
        });

        for (const environment of pipelineConfig.environments) {
            const environmentStage: {
                name: string;
                actions: Array<cdk.aws_codepipeline.CfnPipeline.ActionDeclarationProperty>;
            } = {name: `DeployTo-${environment.name}`, actions: []};

            if (environment.requires_approval) {
                environmentStage.actions.push({
                    actionTypeId: {
                        category: "Approval",
                        owner: "AWS",
                        provider: "Manual",
                        version: "1"
                    },
                    name: `ApprovePromotionTo-${environment.name}`,
                    runOrder: 1
                });
            }

            environmentStage.actions.push({
                name: 'Deploy',
                runOrder: environment.requires_approval ? 2 : 1,
                inputArtifacts: [
                    {name: 'ECRMetadata'},
                ],
                actionTypeId: {
                    category: 'Build',
                    owner: 'AWS',
                    version: '1',
                    provider: 'CodeBuild',
                },
                configuration: {
                    ProjectName: cdk.Fn.ref('BuildProject'),
                    PrimarySource: 'ECRMetadata',
                    EnvironmentVariables: JSON.stringify([
                        {name: 'COPILOT_ENVIRONMENT', value: environment.name},
                        {
                            name: 'ECR_TAG_PATTERN',
                            value: pipelineConfig.tag ? 'tag-latest' : `branch-${pipelineConfig.branch}`
                        },
                    ]),
                },
            });

            (pipeline.stages as Array<cdk.aws_codepipeline.CfnPipeline.StageDeclarationProperty>).push(environmentStage);
        }
    }

    private updateExistingPipeline(pipeline: cdk.aws_codepipeline.CfnPipeline, pipelineConfig: typeof this.codebaseConfiguration['pipelines'][0]) {
        // Update the pipeline name
        pipeline.name = `pipeline-${this.appName}-${this.codebaseConfiguration.name}-${pipelineConfig.name}`;

        // Replace source code action trigger with ECR push
        pipeline.stages[0].actions[0] = {
            name: 'ImagePublished',
            runOrder: 1,
            configuration: {
                RepositoryName: cdk.Fn.ref('ECRRepository'),
                ImageTag: pipelineConfig.tag ? 'tag-latest' : `branch-${pipelineConfig.branch}`,
            },
            outputArtifacts: [{name: 'ECRMetadata'}],
            actionTypeId: {
                category: 'Source',
                owner: 'AWS',
                version: '1',
                provider: 'ECR',
            },
        };

        // Remove build stage
        (pipeline.stages as Array<cdk.aws_codepipeline.CfnPipeline.StageDeclarationProperty>).splice(1, 1);

        // Replace the deployment action in each deploy stage with our custom build script
        const pipelineEnvironments = pipelineConfig.environments.map(e => e.name);
        for (const [index, stage] of (pipeline.stages as Array<cdk.aws_codepipeline.CfnPipeline.StageDeclarationProperty>).entries()) {
            if (stage.name == 'Source') continue;

            const environment = stage.name.replace('DeployTo-', '');

            if (pipelineEnvironments.includes(environment)) {
                pipeline.stages[index].actions[pipeline.stages[index].actions.length - 1] = {
                    name: 'Deploy',
                    //
                    runOrder: pipeline.stages[index].actions.length,
                    inputArtifacts: [
                        {name: 'ECRMetadata'},
                    ],
                    actionTypeId: {
                        category: 'Build',
                        owner: 'AWS',
                        version: '1',
                        provider: 'CodeBuild',
                    },
                    configuration: {
                        ProjectName: cdk.Fn.ref('BuildProject'),
                        PrimarySource: 'ECRMetadata',
                        EnvironmentVariables: JSON.stringify([
                            {name: 'COPILOT_ENVIRONMENT', value: environment},
                            {
                                name: 'ECR_TAG_PATTERN',
                                value: pipelineConfig.tag ? 'tag-latest' : `branch-${pipelineConfig.branch}`,
                            },
                        ]),
                    },
                };
            } else {
                pipeline.stages[index] = undefined;
            }
        }

        pipeline.stages = (pipeline.stages as Array<cdk.aws_codepipeline.CfnPipeline.StageDeclarationProperty>).filter(s => !!s);
    }

    private allowBuildProjectToUseCodestarConnection() {
        const buildProjectPolicy = this.template.getResource("BuildProjectPolicy") as cdk.aws_iam.CfnPolicy;
        (buildProjectPolicy.policyDocument.Statement as Array<any>).push({
            Effect: 'Allow',
            Action: ['codestar-connections:UseConnection'],
            Resource: [this.codestarConnection.arn],
        });
    }

    private allowPipelineToDescribeECRImages() {
        const pipelineRolePolicy = this.template.getResource("PipelineRolePolicy") as cdk.aws_iam.CfnPolicy;
        pipelineRolePolicy.policyDocument.Statement[0].Action.push('ecr:DescribeImages');
    }

    private loadManifestFiles() {
        const pipelineRoot = path.join(process.cwd(), '..');
        const deployRepoRoot = path.join(pipelineRoot, '..', '..', '..');

        // Load copilot pipeline manifest
        this.pipelineManifest = parse(readFileSync(
            path.join(pipelineRoot, 'manifest.yml'),
        ).toString('utf-8')) as PipelineManifest;

        // Load dbt-copilot-tools pipelines configurations
        const pipelinesConfigProperties = parse(readFileSync(
            path.join(deployRepoRoot, 'pipelines.yml'),
        ).toString('utf-8')) as PipelinesConfiguration;

        const codebaseConfiguration = pipelinesConfigProperties.codebases.find(c => c.name === this.pipelineManifest.name);

        if (!codebaseConfiguration) {
            throw new Error(`Could not find a codebase configuration for ${this.pipelineManifest.name}, ensure ./pipelines.yml is up to date`);
        }

        this.codebaseConfiguration = codebaseConfiguration;
    }

    private loadCodestarConnection() {
        const codestarConnections = JSON.parse(execSync('aws codestar-connections list-connections').toString('utf-8')) as CodeStarConnectionListConnectionsOutput;
        const codestarConnectionArn = codestarConnections.Connections
            .find(c => c.ConnectionName === this.pipelineManifest.source.properties.connection_name)?.ConnectionArn;

        const codestarConnectionId = codestarConnectionArn?.split('/').pop();

        if (!codestarConnectionArn || !codestarConnectionId) {
            throw new Error(`Could not find a codestar connection called ${this.pipelineManifest.source.properties.connection_name}, have you created it?`);
        }

        this.codestarConnection = {arn: codestarConnectionArn, id: codestarConnectionId};
    }

    private loadGitRemote() {
        const output = execSync('git remote get-url origin').toString('utf-8');

        if (!output.startsWith('git@')) throw new URIError("Git remote is not an SSH URL.");

        const deployRepository = output.split(':').pop()?.replace('.git', '').replace('\n', '');

        if (!deployRepository) throw new Error("Could not find Git remote.");

        this.deployRepository = deployRepository;
    }
}
