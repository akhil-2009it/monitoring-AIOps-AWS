#!/usr/bin/env python3
"""
Import a pre-trained model into the AIOps platform.

Supported detector types (--detector):
  iforest-logs           sklearn IsolationForest, .joblib
  log-embedding-anomaly  sklearn Pipeline(TfidfVectorizer, IsolationForest), .joblib
  lstm-ae-traces         PyTorch state_dict in `lstm_ae.pt` (with vocab/dim metadata)
  rcf-metrics            SageMaker-built RandomCutForest model.tar.gz
                         (rare; usually retrained in SageMaker — included for completeness)

What this does:
  1. Validate the artifact loads (sanity check before pushing to AWS).
  2. Pack into model.tar.gz with the entry-point script the SageMaker
     inference container expects.
  3. Upload to s3://<models-bucket>/imported/<detector>/<timestamp>/model.tar.gz.
  4. Register as a SageMaker Model Package in the matching ModelPackageGroup
     with status `PendingManualApproval` (override with --auto-approve).
  5. (Optional, with --deploy) Wait for the endpoint to come InService.

Usage:
    python scripts/import_pretrained_model.py \\
        --detector iforest-logs \\
        --artifact ./my_iforest.joblib \\
        --env prod \\
        --models-bucket monitoring-mlops-prod-models \\
        --role-arn arn:aws:iam::ACCOUNT:role/monitoring-mlops-prod-sagemaker-exec-role

After registration, approve in the SageMaker console (or pass --auto-approve).
The existing CodePipeline (`infra /modules/cicd`) handles the deploy.

Manual approval makes the script complete in ~1 minute. Approval → endpoint
InService takes ~25-30 minutes (SageMaker endpoint cold start).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ─── Detector-specific configuration ────────────────────────────────────────

DETECTORS = {
    "iforest-logs": {
        "model_group":          "IForestLogsModelGroup",
        "endpoint":              "iforest-logs",
        "framework":             "sklearn",
        "framework_version":     "1.2-1",
        "py_version":            "py3",
        "default_instance_type": "ml.m5.large",
        "expected_extension":    ".joblib",
        "container_image_pattern": (
            "246618743249.dkr.ecr.{region}.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3"
        ),
    },
    "log-embedding-anomaly": {
        "model_group":          "LogEmbeddingAnomalyModelGroup",
        "endpoint":              "log-embedding-anomaly",
        "framework":             "sklearn",
        "framework_version":     "1.2-1",
        "py_version":            "py3",
        "default_instance_type": "ml.c5.xlarge",
        "expected_extension":    ".joblib",
        "container_image_pattern": (
            "246618743249.dkr.ecr.{region}.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3"
        ),
    },
    "lstm-ae-traces": {
        "model_group":          "LSTMAETracesModelGroup",
        "endpoint":              "lstm-ae-traces",
        "framework":             "pytorch",
        "framework_version":     "2.1",
        "py_version":            "py310",
        "default_instance_type": "ml.c5.large",
        "expected_extension":    ".pt",
        # Region-specific PyTorch inference image; see SageMaker docs for current digest.
        "container_image_pattern": (
            "763104351884.dkr.ecr.{region}.amazonaws.com/pytorch-inference:2.1-cpu-py310"
        ),
    },
    "rcf-metrics": {
        "model_group":          "RCFMetricsModelGroup",
        "endpoint":              "rcf-metrics",
        "framework":             "rcf",
        "framework_version":     "1",
        "py_version":            "n/a",
        "default_instance_type": "ml.t2.medium",
        "expected_extension":    ".tar.gz",  # native SageMaker artifact
        # Region-specific built-in image; resolved via boto3.image_uris in main()
        "container_image_pattern": "BUILTIN",
    },
}


# ─── Inference entrypoints (written into the model archive) ─────────────────

INFERENCE_SCRIPT_SKLEARN = """
\"\"\"SageMaker inference handlers for sklearn pre-trained models.\"\"\"
import json, os
import joblib
import numpy as np


def model_fn(model_dir):
    return joblib.load(os.path.join(model_dir, "model.joblib"))


def input_fn(body, content_type):
    if content_type and "application/json" in content_type:
        rec = json.loads(body)
        # Two accepted shapes:
        #   {"features": [[...], ...]}    → numeric matrix
        #   {"text": ["log line", ...]}   → strings (for the TF-IDF pipeline)
        if "features" in rec:
            return ("features", np.asarray(rec["features"], dtype=float))
        if "text" in rec:
            return ("text", list(rec["text"]))
    raise ValueError("Expected JSON with 'features' or 'text' key")


def predict_fn(input_data, model):
    kind, X = input_data
    if hasattr(model, "score_samples"):
        anomaly_score = -model.score_samples(X)   # higher = more anomalous
    else:                                          # sklearn Pipeline
        # Score the inner IsolationForest if wrapped in a Pipeline
        steps = getattr(model, "steps", None)
        clf = steps[-1][1] if steps else model
        # Transform if pipeline
        Xt = model.named_steps[steps[0][0]].transform(X) if steps and kind == "text" else X
        anomaly_score = -clf.score_samples(Xt)
    is_anomaly = (anomaly_score >= np.percentile(anomaly_score, 99)).tolist() \\
                 if len(anomaly_score) >= 100 else (anomaly_score > 0.5).tolist()
    return {"score": anomaly_score.tolist(), "is_anomaly": is_anomaly}


def output_fn(prediction, accept):
    return json.dumps(prediction), "application/json"
"""

INFERENCE_SCRIPT_PYTORCH = """
\"\"\"SageMaker inference handlers for the LSTM autoencoder.\"\"\"
import json, os
import torch
import torch.nn as nn


class LSTMAE(nn.Module):
    def __init__(self, input_dim, hidden_dim):
        super().__init__()
        self.encoder = nn.LSTM(input_dim, hidden_dim, batch_first=True)
        self.decoder = nn.LSTM(hidden_dim, hidden_dim, batch_first=True)
        self.out = nn.Linear(hidden_dim, input_dim)

    def forward(self, x):
        _, (h, c) = self.encoder(x)
        T = x.size(1)
        z = h[-1].unsqueeze(1).expand(-1, T, -1)
        d, _ = self.decoder(z, (h, c))
        return self.out(d)


def model_fn(model_dir):
    ckpt = torch.load(os.path.join(model_dir, "lstm_ae.pt"), map_location="cpu", weights_only=False)
    m = LSTMAE(ckpt["feature_dim"], ckpt["hidden_dim"])
    m.load_state_dict(ckpt["state_dict"])
    m.eval()
    return {"model": m, "vocab": ckpt["vocab"], "max_seq_len": ckpt["max_seq_len"], "feature_dim": ckpt["feature_dim"]}


def input_fn(body, content_type):
    rec = json.loads(body)
    return rec.get("spans", [])   # list of [(svc_id, op_id, dur_ms, status), ...]


def predict_fn(spans, ctx):
    m, vocab, max_len, feat_dim = ctx["model"], ctx["vocab"], ctx["max_seq_len"], ctx["feature_dim"]
    num_services = vocab["num_services"]; num_ops = vocab["num_ops"]
    X = torch.zeros(1, max_len, feat_dim); mask = torch.zeros(1, max_len)
    for t, span in enumerate(spans[:max_len]):
        svc, op, dur, status = span
        X[0, t, svc] = 1.0
        X[0, t, num_services + op] = 1.0
        X[0, t, -2] = min(dur / 1000.0, 60.0)
        X[0, t, -1] = float(status)
        mask[0, t] = 1.0
    with torch.no_grad():
        recon = m(X)
        err = ((recon - X) ** 2).mean(dim=2)
        score = (err * mask).sum().item() / max(mask.sum().item(), 1)
    return {"score": score, "is_anomaly": score > 1.0}


def output_fn(prediction, accept):
    return json.dumps(prediction), "application/json"
"""


# ─── Validation: load the model locally before pushing it to AWS ─────────────

def validate_artifact(detector: str, artifact: Path) -> dict:
    """Try to load the model. Return a small metadata dict for the registry."""
    if detector in ("iforest-logs", "log-embedding-anomaly"):
        try:
            import joblib
        except ImportError:
            sys.exit("joblib required for sklearn validation. pip install joblib scikit-learn")
        model = joblib.load(artifact)
        # IsolationForest or Pipeline ending in IF
        steps = getattr(model, "steps", None)
        clf = steps[-1][1] if steps else model
        if not hasattr(clf, "score_samples"):
            sys.exit(f"Loaded object is not an IsolationForest/sklearn-compatible: {type(model)}")
        info = {
            "type":          type(model).__name__,
            "n_features":    int(getattr(clf, "n_features_in_", 0)),
            "contamination": float(getattr(clf, "contamination", 0)) if hasattr(clf, "contamination") else None,
        }
        if steps:
            info["pipeline_steps"] = [s[0] for s in steps]
        return info

    if detector == "lstm-ae-traces":
        try:
            import torch
        except ImportError:
            sys.exit("torch required for LSTM validation. pip install torch")
        ckpt = torch.load(artifact, map_location="cpu", weights_only=False)
        for required in ("state_dict", "feature_dim", "hidden_dim", "max_seq_len", "vocab"):
            if required not in ckpt:
                sys.exit(f"PyTorch checkpoint missing required key: {required!r}")
        return {
            "type":         "LSTMAE",
            "feature_dim":  int(ckpt["feature_dim"]),
            "hidden_dim":   int(ckpt["hidden_dim"]),
            "max_seq_len":  int(ckpt["max_seq_len"]),
            "num_services": int(ckpt["vocab"].get("num_services", 0)),
            "num_ops":      int(ckpt["vocab"].get("num_ops", 0)),
        }

    if detector == "rcf-metrics":
        # RCF artifacts are SageMaker-native binaries — we can't really inspect them
        # client-side. Just confirm the tarball is well-formed.
        if not tarfile.is_tarfile(artifact):
            sys.exit(f"{artifact} is not a valid tar.gz")
        with tarfile.open(artifact) as t:
            members = t.getnames()
        return {"type": "RCF", "tar_members": members[:20]}

    sys.exit(f"Unknown detector: {detector}")


# ─── Build the model.tar.gz ───────────────────────────────────────────────────

def build_archive(detector: str, artifact: Path, work_dir: Path) -> Path:
    """Stage artifact + inference script into a model.tar.gz at work_dir."""
    cfg = DETECTORS[detector]
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / "model.tar.gz"

    if detector == "rcf-metrics":
        # Pass through — already a tarball
        shutil.copy(artifact, out)
        return out

    stage = work_dir / "stage"
    code  = stage / "code"
    code.mkdir(parents=True, exist_ok=True)

    if detector in ("iforest-logs", "log-embedding-anomaly"):
        shutil.copy(artifact, stage / "model.joblib")
        (code / "inference.py").write_text(INFERENCE_SCRIPT_SKLEARN.lstrip())
        (code / "requirements.txt").write_text("scikit-learn==1.2.1\njoblib==1.3.0\n")
    elif detector == "lstm-ae-traces":
        shutil.copy(artifact, stage / "lstm_ae.pt")
        (code / "inference.py").write_text(INFERENCE_SCRIPT_PYTORCH.lstrip())
        (code / "requirements.txt").write_text("torch==2.1.0\n")
    else:
        sys.exit(f"build_archive: unsupported detector {detector}")

    with tarfile.open(out, "w:gz") as t:
        for f in stage.rglob("*"):
            t.add(f, arcname=f.relative_to(stage))
    logger.info("Built %s (%.1f KB)", out, out.stat().st_size / 1024)
    return out


# ─── Upload to S3 ─────────────────────────────────────────────────────────────

def upload_artifact(boto, bucket: str, key: str, local_path: Path) -> str:
    boto.client("s3").upload_file(str(local_path), bucket, key)
    uri = f"s3://{bucket}/{key}"
    logger.info("Uploaded artifact -> %s", uri)
    return uri


# ─── Register as a Model Package ─────────────────────────────────────────────

def resolve_image_uri(detector: str, region: str) -> str:
    cfg = DETECTORS[detector]
    if cfg["container_image_pattern"] == "BUILTIN":
        # Resolve via SageMaker SDK
        try:
            from sagemaker.image_uris import retrieve
        except ImportError:
            sys.exit("Install sagemaker for RCF: pip install sagemaker")
        return retrieve(framework="randomcutforest", region=region, version="1")
    return cfg["container_image_pattern"].format(region=region)


def register_model_package(
    boto,
    detector: str,
    region: str,
    s3_uri: str,
    instance_type: str,
    metadata: dict,
    auto_approve: bool,
) -> str:
    cfg = DETECTORS[detector]
    sm = boto.client("sagemaker", region_name=region)
    image_uri = resolve_image_uri(detector, region)

    inference_specification: dict[str, Any] = {
        "Containers": [
            {
                "Image": image_uri,
                "ModelDataUrl": s3_uri,
                # For sklearn / pytorch script-mode containers, point at inference.py
                **(
                    {"Environment": {"SAGEMAKER_PROGRAM": "inference.py", "SAGEMAKER_SUBMIT_DIRECTORY": s3_uri}}
                    if detector != "rcf-metrics" else {}
                ),
            }
        ],
        "SupportedContentTypes":   ["application/json"],
        "SupportedResponseMIMETypes": ["application/json"],
        "SupportedRealtimeInferenceInstanceTypes": [instance_type],
        "SupportedTransformInstanceTypes":         ["ml.m5.large"],
    }

    resp = sm.create_model_package(
        ModelPackageGroupName=cfg["model_group"],
        ModelPackageDescription=(
            f"Imported pre-trained {detector} model. "
            f"Validated: {json.dumps(metadata)[:500]}"
        ),
        InferenceSpecification=inference_specification,
        ModelApprovalStatus="Approved" if auto_approve else "PendingManualApproval",
        MetadataProperties={
            "GeneratedBy": "scripts/import_pretrained_model.py",
        },
        CustomerMetadataProperties={
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "detector":    detector,
            **{k: str(v) for k, v in metadata.items() if not isinstance(v, list)},
        },
    )
    arn = resp["ModelPackageArn"]
    logger.info("Registered ModelPackage: %s (status=%s)",
                arn, "Approved" if auto_approve else "PendingManualApproval")
    return arn


# ─── Wait for endpoint InService ────────────────────────────────────────────

def wait_for_endpoint(boto, endpoint_name: str, region: str, timeout_sec: int = 1800) -> bool:
    sm = boto.client("sagemaker", region_name=region)
    started = time.time()
    while time.time() - started < timeout_sec:
        try:
            status = sm.describe_endpoint(EndpointName=endpoint_name)["EndpointStatus"]
        except sm.exceptions.ClientError as exc:
            logger.info("Endpoint %s does not exist yet: %s", endpoint_name, exc.response["Error"]["Code"])
            time.sleep(30); continue
        logger.info("Endpoint %s status=%s (%.0fs elapsed)",
                    endpoint_name, status, time.time() - started)
        if status == "InService":
            return True
        if status in ("Failed", "RollingBack"):
            logger.error("Endpoint deployment failed: %s", status)
            return False
        time.sleep(30)
    logger.error("Timed out after %ds waiting for endpoint", timeout_sec)
    return False


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--detector", required=True, choices=list(DETECTORS.keys()))
    p.add_argument("--artifact", required=True, type=Path, help="Local path to .joblib / .pt / .tar.gz")
    p.add_argument("--env", required=True, choices=["dev", "qa", "prod"])
    p.add_argument("--region", default=os.getenv("AWS_REGION", "ap-south-1"))
    p.add_argument("--models-bucket", required=True)
    p.add_argument("--role-arn", default=os.getenv("SAGEMAKER_EXEC_ROLE_ARN"),
                   help="(reserved; CodePipeline performs the deploy with its own role)")
    p.add_argument("--instance-type", default="",
                   help=f"Override default instance for the detector. Defaults: "
                        + ", ".join(f"{k}={v['default_instance_type']}" for k, v in DETECTORS.items()))
    p.add_argument("--auto-approve", action="store_true",
                   help="Register with status=Approved. Default is PendingManualApproval (safer).")
    p.add_argument("--wait-for-endpoint", action="store_true",
                   help="Block until the endpoint is InService (after manual approval).")
    args = p.parse_args()

    if not args.artifact.exists():
        sys.exit(f"Artifact not found: {args.artifact}")

    cfg = DETECTORS[args.detector]
    instance_type = args.instance_type or cfg["default_instance_type"]
    endpoint_name = f"{cfg['endpoint']}-{args.env}"

    # 1. Validate
    logger.info("[1/5] Validating artifact...")
    metadata = validate_artifact(args.detector, args.artifact)
    logger.info("      validated: %s", metadata)

    # 2. Build archive
    logger.info("[2/5] Building model archive...")
    with tempfile.TemporaryDirectory() as tmp:
        archive = build_archive(args.detector, args.artifact, Path(tmp))

        # 3. Upload
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        key = f"imported/{args.detector}/{ts}/model.tar.gz"
        try:
            import boto3
        except ImportError:
            sys.exit("boto3 required. pip install boto3 sagemaker")
        s3_uri = upload_artifact(boto3, args.models_bucket, key, archive)

        # 4. Register
        logger.info("[3/5] Registering ModelPackage...")
        arn = register_model_package(
            boto3, args.detector, args.region,
            s3_uri, instance_type, metadata,
            auto_approve=args.auto_approve,
        )

    # 5. Hand off
    logger.info("[4/5] Done — handed off to CodePipeline.")
    print()
    print("════════════════════════════════════════════════════════════════════")
    print(f"Model registered: {arn}")
    print(f"Group:            {cfg['model_group']}")
    print(f"Status:           {'Approved' if args.auto_approve else 'PendingManualApproval'}")
    print(f"Target endpoint:  {endpoint_name}")
    print(f"Instance type:    {instance_type}")
    print()
    if not args.auto_approve:
        print("Next steps:")
        print(f"  1. Open SageMaker → Model Registry → {cfg['model_group']}")
        print(f"  2. Review the package, then click 'Approve'.")
        print(f"  3. CodePipeline `monitoring-mlops-{args.env}-{cfg['endpoint']}-promotion`")
        print( "     will deploy automatically (~25 min).")
    else:
        print("Auto-approved. CodePipeline should pick up shortly (~25 min to InService).")
    print()
    print("Once endpoint is InService, set the env var on the API:")
    env_var = {
        "rcf-metrics":           "MLOPS_ENDPOINT_RCF_METRICS",
        "iforest-logs":          "MLOPS_ENDPOINT_IFOREST_LOGS",
        "lstm-ae-traces":        "MLOPS_ENDPOINT_LSTM_AE_TRACES",
        "log-embedding-anomaly": "MLOPS_ENDPOINT_LOG_EMBEDDING_ANOMALY",
    }[args.detector]
    print(f"  kubectl -n api set env deployment/anomaly-scoring-api {env_var}={endpoint_name}")
    print(f"  kubectl -n api rollout status deployment/anomaly-scoring-api")
    print("════════════════════════════════════════════════════════════════════")

    # 6. Optional: block on endpoint
    if args.wait_for_endpoint:
        logger.info("[5/5] Waiting for endpoint %s to become InService...", endpoint_name)
        if not wait_for_endpoint(boto3, endpoint_name, args.region):
            sys.exit(2)
        logger.info("✅ Endpoint is InService.")


if __name__ == "__main__":
    main()
