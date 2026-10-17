"""CDK apps read statically (no synth): constructs from a versioned table, loops over literal arrays expanded."""

from __future__ import annotations

from deriva.adapters.treesitter.cdk import CdkConstruct, cdk_resources

CONSTRUCTS = {
    "aws-ecs.FargateService": CdkConstruct(type="AWS::ECS::Service", environment="AWS ECS Fargate"),
    "aws-rds.DatabaseInstance": CdkConstruct(type="AWS::RDS::DBInstance"),
    "aws-elasticache.CfnReplicationGroup": CdkConstruct(type="AWS::ElastiCache::ReplicationGroup"),
    "aws-elasticloadbalancingv2.ApplicationLoadBalancer": CdkConstruct(type="AWS::ElasticLoadBalancingV2::LoadBalancer", properties=(("Type", "application"),)),
    "aws-s3.Bucket": CdkConstruct(type="AWS::S3::Bucket"),
}

SERVICES = """
import * as cdk from 'aws-cdk-lib';
import * as ecs from 'aws-cdk-lib/aws-ecs';

interface Config { name: string; port: number }

const CONFIGS: Config[] = [
  { name: 'alpha', port: 8001 },
  { name: 'beta', port: 8002 },
];

export class Services extends cdk.Stack {
  constructor(scope: any, id: string) {
    super(scope, id);
    for (const config of CONFIGS) {
      this.create(config);
    }
  }

  private create(config: Config): ecs.FargateService {
    const serviceName = `${config.name}-service`;
    return new ecs.FargateService(this, `${config.name}Service`, { serviceName, desiredCount: 1 });
  }
}
"""

DATA = """
import * as rds from 'aws-cdk-lib/aws-rds';
import { CfnReplicationGroup } from 'aws-cdk-lib/aws-elasticache';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sns from 'aws-cdk-lib/aws-sns';

export class Data {
  constructor(scope: any) {
    const db = new rds.DatabaseInstance(scope, 'Db', { engine: rds.DatabaseInstanceEngine.postgres({ version: rds.PostgresEngineVersion.VER_16 }) });
    const cache = new CfnReplicationGroup(scope, 'Cache', { engine: 'redis' });
    const lb = new elbv2.ApplicationLoadBalancer(scope, 'Lb', {});
    for (const n of ['one', 'two']) {
      new s3.Bucket(scope, `${n}Bucket`);
    }
    new sns.Topic(scope, 'Alarms');  // not in the table
  }
}
"""


def test_a_construct_in_a_method_called_per_array_entry_is_one_resource_per_entry():
    resources = cdk_resources({"app/infra/lib/services.ts": SERVICES}, CONSTRUCTS, properties=("Engine", "Type"))

    services = resources["app/infra/lib/services.ts"]
    assert services == {
        "alphaService": {"Type": "AWS::ECS::Service", "Properties": {}, "Names": ["alphaService", "alpha-service"], "Environment": "AWS ECS Fargate"},
        "betaService": {"Type": "AWS::ECS::Service", "Properties": {}, "Names": ["betaService", "beta-service"], "Environment": "AWS ECS Fargate"},
    }


def test_engines_and_fixed_properties_qualify_resources_and_unknown_constructs_are_left_out():
    resources = cdk_resources({"app/infra/lib/data.ts": DATA}, CONSTRUCTS, properties=("Engine", "Type"))["app/infra/lib/data.ts"]

    assert {k: (r["Type"], r["Properties"]) for k, r in resources.items()} == {
        "Db": ("AWS::RDS::DBInstance", {"Engine": "postgres"}),
        "Cache": ("AWS::ElastiCache::ReplicationGroup", {"Engine": "redis"}),
        "Lb": ("AWS::ElasticLoadBalancingV2::LoadBalancer", {"Type": "application"}),
        "oneBucket": ("AWS::S3::Bucket", {}),
        "twoBucket": ("AWS::S3::Bucket", {}),
    }


def test_files_without_constructs_give_nothing():
    assert cdk_resources({"app/infra/bin/app.ts": "const x = 1;\n"}, CONSTRUCTS, properties=()) == {}
