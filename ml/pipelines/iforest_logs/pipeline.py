"""Isolation Forest on tabular log features."""
from __future__ import annotations
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
SHARED   = CODE_DIR.parent / "_shared"


def build_pipeline(config):
    from sagemaker.inputs import TrainingInput
    from sagemaker.processing import ProcessingInput, ProcessingOutput
    from sagemaker.sklearn.estimator import SKLearn
    from sagemaker.workflow.parameters import ParameterString
    from sagemaker.workflow.pipeline import Pipeline
    from sagemaker.workflow.steps import TrainingStep

    from ml.pipelines._shared.pipeline_helpers import (
        build_evaluation_step,
        build_processing_step,
        build_register_step_with_gate,
        common_parameters,
        pipeline_session,
    )

    sm_session = pipeline_session(config.region)
    params = common_parameters()
    input_data_uri = ParameterString(
        name="input_data_uri",
        default_value=f"s3://{config.bucket}/processed/logs/",
    )

    validation_step = build_processing_step(
        config=config,
        step_name="DataValidation",
        code_path=str(SHARED / "data_validation.py"),
        inputs=[ProcessingInput(source=input_data_uri, destination="/opt/ml/processing/input")],
        outputs=[ProcessingOutput(output_name="validation", source="/opt/ml/processing/output")],
        arguments=["--min-rows", "500"],
    )

    extract_step = build_processing_step(
        config=config,
        step_name="LogFeatureExtract",
        code_path=str(CODE_DIR / "feature_extract.py"),
        inputs=[ProcessingInput(source=input_data_uri, destination="/opt/ml/processing/input")],
        outputs=[
            ProcessingOutput(output_name="train", source="/opt/ml/processing/train"),
            ProcessingOutput(output_name="test",  source="/opt/ml/processing/test"),
        ],
    )
    extract_step.add_depends_on([validation_step])

    estimator = SKLearn(
        entry_point="train.py",
        source_dir=str(CODE_DIR),
        role=config.role_arn,
        instance_type=config.instance_type_train,
        framework_version="1.2-1",
        py_version="py3",
        sagemaker_session=sm_session,
        use_spot_instances=config.use_spot,
        max_run=config.max_runtime_sec,
        max_wait=config.max_wait_sec if config.use_spot else None,
        output_path=f"s3://{config.bucket}/models/{config.model_name}/{config.environment}/",
        base_job_name=config.base_job_name,
    )

    train_step = TrainingStep(
        name="Train",
        estimator=estimator,
        inputs={
            "train": TrainingInput(
                s3_data=extract_step.properties.ProcessingOutputConfig.Outputs["train"].S3Output.S3Uri,
                content_type="text/csv",
            ),
        },
    )

    eval_step, eval_pf = build_evaluation_step(
        config=config,
        code_path=str(CODE_DIR / "evaluate.py"),
        training_step=train_step,
        eval_data_input=extract_step.properties.ProcessingOutputConfig.Outputs["test"].S3Output.S3Uri,
    )

    register_step = build_register_step_with_gate(
        config=config,
        training_step=train_step,
        eval_step=eval_step,
        eval_property_file=eval_pf,
        primary_metric_name="metrics.precision_at_top1pct",
        gate_op=">=",
        gate_threshold=config.metric_gate.get("precision_at_top1pct", 0.80),
    )

    return Pipeline(
        name=config.pipeline_name,
        parameters=list(params.values()) + [input_data_uri],
        steps=[validation_step, extract_step, train_step, eval_step, register_step],
        sagemaker_session=sm_session,
    )
