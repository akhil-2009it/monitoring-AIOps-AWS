# AIOps Platform Architecture (concise)

```
DATA SOURCES (L1)
  CloudFront · ALB · WAF · App · EKS · NGINX · Kafka · MySQL · Mongo ·
  Redis · Node/Container/Prom metrics · OTEL traces

         │
         ▼

INGESTION (L2)
  ┌─────────────────────────────┐         ┌──────────────────────────┐
  │ Kinesis Firehose            │         │ MSK (Kafka)              │
  │ CloudFront/ALB/WAF/App/EKS  │         │ App / NGINX / Mongo /    │
  │ /MySQL → S3 raw Parquet     │         │ Redis  via Fluent Bit    │
  └─────────────┬───────────────┘         └────────────┬─────────────┘
                │                                      │
                ▼                                      ▼
                ┌──────────────────────────────────────────┐
                │ S3 raw   (security-lake-shaped, per-src)  │
                │ S3 processed   (Glue ETL, common-schema)  │
                │ S3 features    (FeatureStore offline)     │
                │ S3 anomalies   (detector outputs)         │
                │ S3 security_lake (GuardDuty findings)     │
                └────────┬───────────────────┬─────────────┘
                         │                   │
                         ▼                   ▼
INDEX (L3)        ┌──────────────┐    ┌──────────────┐
                  │ OpenSearch   │    │ Glue catalog │
                  │ + AD plugin  │    │ Athena       │
                  └──┬───────────┘    └──────────────┘
                     │
                     ▼
DETECTION (L5, tiered)
  ┌────────────────────────────────────────────────────────────────────┐
  │ AWS-managed:    GuardDuty · Security Hub · Detective              │
  │ Streaming:      Lambda(z-score, EWMA, rate, threshold)            │
  │ OpenSearch AD:  RCF on indexed time-series                        │
  │ SageMaker:                                                         │
  │    1. RCF metrics            (numeric metric streams)             │
  │    2. Isolation Forest logs  (tabular log features)               │
  │    3. LSTM autoencoder       (OTEL trace span sequences)          │
  │    4. Log-embedding (TF-IDF + IForest, swap to LogBERT later)     │
  └────────────────┬───────────────────────────────────────────────────┘
                   │
                   ▼
                          ┌────────────────────────────────────┐
                          │ Cognito User Pool                   │
                          │ groups: analyst | responder | admin │
                          └─────────────┬──────────────────────┘
                                        │ JWT
                                        ▼
                                 ┌─────────────┐  WAFv2  ┌────────────────────────┐
                                 │ ALB (HTTPS) │────────►│ EKS                     │
                                 └──────┬──────┘         │ anomaly-scoring-api    │
                                        │                 │ /score /alerts /...    │
                                        ▼                 └──┬─────────────┬──────┘
                                                            │             │
                                                            │             ▼
                                                            │      SageMaker Endpoints
                                                            │     (rcf-metrics, iforest-logs,
                                                            │      lstm-ae-traces, log-embed)
                                                            ▼
                                                     OpenSearch (queries)
                                                     S3 anomalies (write)

OBSERVABILITY (L7)
  AMP (Prometheus remote-write)  ←─── ADOT collector ←─── EKS pods
  AMG (Grafana, federated)
  X-Ray (traces)
  CloudWatch (alarms + dashboards)

EVENT LOOP
  Drift on detector inputs → CloudWatch alarm → EventBridge →
  Lambda → SageMaker Pipeline retrain → Model Registry approve → endpoint update
```
