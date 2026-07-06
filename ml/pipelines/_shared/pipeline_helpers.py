"""
Shared SageMaker Pipeline scaffolding.

All four model pipelines follow the same shape (CLAUDE.md):
    data_validation_step → feature_extraction_step → training_step
                          → evaluation_step → register_step (gated)

This module factors out the boilerplate (sessions, parameters, processing-job
construction, conditional register on metric gate) so the per-model pipeline
files only declare what's unique:
  - the training image / estimator
  - the metric gate threshold
  - any model-specific processing logic

Designed to run in two modes:
  - Authoring (`upsert`)  : registers the pipeline definition.
  - Execution (`start`)    : starts a run with parameters.

Both are CLI-controlled via run_pipeline.py in each model directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping

import boto3

# SageMaker SDK imports are deferred to function bodies so this file imports
# even in unit tests where the SageMaker SDK isn't installed.


@dataclass
class PipelineConfig:
    model_name: str                   # e.g. "perf-predictor"
    model_group_name: str             # e.g. "PerformancePredictorModelGroup"
    environment: str                  # dev | qa | prod
    region: str
    role_arn: str
    bucket: str                       # main project data bucket (features / models)
    feature_group_name: str
    metric_gate: Mapping[str, float]  # e.g. {"rmse": 8.0, "r2_min": 0.75}
    instance_type_train: str = "ml.m5.xlarge"
    instance_type_process: str = "ml.m5.xlarge"
    use_spot: bool = True
    max_runtime_sec: int = 60 * 60 * 4
    max_wait_sec: int = 60 * 60 * 5   # if use_spot
    image_uri_override: str | None = None
    framework_version: str = "1.7-1"  # XGBoost default; overridden per pipeline
    pipeline_kwargs: dict = field(default_factory=dict)

    @property
    def pipeline_name(self) -> str:
        return f"{self.model_name}-{self.environment}-pipeline"

    @property
    def base_job_name(self) -> str:
        return f"{self.model_name}-{self.environment}"


def sagemaker_session(region: str):
    import sagemaker
    return sagemaker.Session(boto_session=boto3.Session(region_name=region))


def pipeline_session(region: str):
    from sagemaker.workflow.pipeline_context import PipelineSession
    return PipelineSession(boto_session=boto3.Session(region_name=region))


def common_parameters():
    """Pipeline parameters present on every pipeline run."""
    from sagemaker.workflow.parameters import (
        ParameterInteger,
        ParameterString,
    )

    return {
        "trigger": ParameterString(name="trigger", default_value="manual"),
        "alarm_name": ParameterString(name="alarm_name", default_value=""),
        "training_instance_count": ParameterInteger(name="training_instance_count", default_value=1),
    }


def build_processing_step(
    config: PipelineConfig,
    step_name: str,
    code_path: str,
    arguments: list[str] | None = None,
    inputs: list | None = None,
    outputs: list | None = None,
) -> Any:
    """Build a SageMaker Processing step using SKLearnProcessor (cheap, generic)."""
    from sagemaker.sklearn.processing import SKLearnProcessor
    from sagemaker.workflow.steps import ProcessingStep

    processor = SKLearnProcessor(
        framework_version="1.2-1",
        role=config.role_arn,
        instance_type=config.instance_type_process,
        instance_count=1,
        sagemaker_session=pipeline_session(config.region),
        base_job_name=f"{config.base_job_name}-{step_name}",
    )

    return ProcessingStep(
        name=step_name,
        processor=processor,
        code=code_path,
        inputs=inputs or [],
        outputs=outputs or [],
        job_arguments=arguments or [],
    )


def build_evaluation_step(
    config: PipelineConfig,
    code_path: str,
    training_step,
    eval_data_input,
) -> tuple[Any, Any]:
    """Returns (eval_step, evaluation_property_file) for use in the register gate."""
    from sagemaker.processing import (
        ProcessingInput,
        ProcessingOutput,
    )
    from sagemaker.sklearn.processing import SKLearnProcessor
    from sagemaker.workflow.properties import PropertyFile
    from sagemaker.workflow.steps import ProcessingStep

    processor = SKLearnProcessor(
        framework_version="1.2-1",
        role=config.role_arn,
        instance_type=config.instance_type_process,
        instance_count=1,
        sagemaker_session=pipeline_session(config.region),
        base_job_name=f"{config.base_job_name}-evaluate",
    )

    evaluation_report = PropertyFile(
        name="EvaluationReport",
        output_name="evaluation",
        path="evaluation.json",
    )

    step = ProcessingStep(
        name="Evaluate",
        processor=processor,
        code=code_path,
        inputs=[
            ProcessingInput(
                source=training_step.properties.ModelArtifacts.S3ModelArtifacts,
                destination="/opt/ml/processing/model",
            ),
            ProcessingInput(
                source=eval_data_input,
                destination="/opt/ml/processing/eval",
            ),
        ],
        outputs=[
            ProcessingOutput(output_name="evaluation", source="/opt/ml/processing/output"),
        ],
        property_files=[evaluation_report],
    )
    return step, evaluation_report


def build_register_step_with_gate(
    config: PipelineConfig,
    training_step,
    eval_step,
    eval_property_file,
    primary_metric_name: str,
    gate_op: str,
    gate_threshold: float,
    inference_instances: list[str] | None = None,
    transform_instances: list[str] | None = None,
):
    """
    Conditional model registration: only register if the eval JSON has
    primary_metric matching gate_op vs threshold (e.g. "rmse" < 8.0).
    """
    from sagemaker.workflow.condition_step import ConditionStep
    from sagemaker.workflow.conditions import (
        ConditionGreaterThanOrEqualTo,
        ConditionLessThanOrEqualTo,
    )
    from sagemaker.workflow.functions import JsonGet
    from sagemaker.workflow.step_collections import RegisterModel

    metrics_uri = eval_step.properties.ProcessingOutputConfig.Outputs["evaluation"].S3Output.S3Uri

    register = RegisterModel(
        name="RegisterModel",
        estimator=training_step.estimator,
        model_data=training_step.properties.ModelArtifacts.S3ModelArtifacts,
        content_types=["application/json"],
        response_types=["application/json"],
        inference_instances=inference_instances or ["ml.t2.medium"],
        transform_instances=transform_instances or ["ml.m5.large"],
        model_package_group_name=config.model_group_name,
        approval_status="PendingManualApproval",
        # Production-safety: every package gets the same metric file attached
        # so the registry shows the metrics that earned it the registration.
        model_metrics=_build_model_metrics(metrics_uri),
    )

    # Build the condition. Use Less/GreaterThanOrEqualTo for the common cases.
    metric_value = JsonGet(
        step_name=eval_step.name,
        property_file=eval_property_file,
        json_path=primary_metric_name,
    )

    if gate_op == "<=":
        cond = ConditionLessThanOrEqualTo(left=metric_value, right=gate_threshold)
    elif gate_op == ">=":
        cond = ConditionGreaterThanOrEqualTo(left=metric_value, right=gate_threshold)
    else:
        raise ValueError(f"Unsupported gate_op: {gate_op!r}")

    return ConditionStep(
        name="GateOnMetric",
        conditions=[cond],
        if_steps=[register],
        else_steps=[],
    )


def _build_model_metrics(metrics_s3_uri):
    from sagemaker.model_metrics import MetricsSource, ModelMetrics

    return ModelMetrics(
        model_statistics=MetricsSource(
            s3_uri=metrics_s3_uri,
            content_type="application/json",
        )
    )
