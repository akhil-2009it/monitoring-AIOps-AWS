from __future__ import annotations
import argparse, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from ml.pipelines._shared.pipeline_helpers import PipelineConfig
from ml.pipelines.log_embedding_anomaly.pipeline import build_pipeline


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--env", required=True, choices=["dev","qa","prod"])
    p.add_argument("--region", default=os.getenv("AWS_REGION", "ap-south-1"))
    p.add_argument("--role-arn", default=os.getenv("SAGEMAKER_EXEC_ROLE_ARN"))
    p.add_argument("--bucket",   default=os.getenv("MODELS_BUCKET"))
    p.add_argument("--upsert-only", action="store_true")
    args = p.parse_args()
    if not args.role_arn or not args.bucket: sys.exit("Set --role-arn and --bucket")

    config = PipelineConfig(
        model_name="log-embedding-anomaly",
        model_group_name="LogEmbeddingAnomalyModelGroup",
        environment=args.env, region=args.region,
        role_arn=args.role_arn, bucket=args.bucket,
        feature_group_name="monitoring-mlops-log-lines-v1",
        metric_gate={"precision_at_top1pct": 0.75},
        instance_type_train="ml.m5.2xlarge",
    )
    pipeline = build_pipeline(config)
    pipeline.upsert(role_arn=config.role_arn)
    print(f"Upserted: {config.pipeline_name}")
    if not args.upsert_only:
        ex = pipeline.start(parameters={"trigger":"manual"})
        print(f"Started: {ex.arn}")


if __name__ == "__main__":
    main()
