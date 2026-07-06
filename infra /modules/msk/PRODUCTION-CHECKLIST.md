# MSK — Production Checklist

## What this module creates
- MSK cluster (3 brokers default), TLS + SASL/IAM auth
- KMS encryption at rest + in transit + in-cluster
- JMX + node_exporter Prometheus endpoints (scraped by ADOT)
- CloudWatch logs for broker events
- Server config: 3-replica, min.insync.replicas=2, 72h retention

## Pre-apply gates
- [ ] **broker_instance_type** — `kafka.t3.small` is fine for dev (~$33/broker/month). Production sustained throughput → `kafka.m5.large` (~$165/broker/month) at minimum.
- [ ] **broker_count** — must be a multiple of subnet count (3 AZs → 3, 6, or 9 brokers).
- [ ] **ebs_volume_size_gb** — 100 GB allows ~3 days of retention at modest log volume. Monitor `KafkaDataLogsDiskUsed` and bump before 80%.
- [ ] **`auto.create.topics.enable=false`** — strict: every topic must be created explicitly. Add a topic creation step in CI to provision: `logs.app`, `logs.nginx`, `logs.kafka`, `logs.mongo`, `logs.redis`, `logs.dlq`.
- [ ] **client_authentication_iam = true** — Fluent Bit, Kafka Connect, and the scoring API all use IRSA roles to talk to MSK. Verify the IRSA roles have `kafka-cluster:*` permissions scoped to specific topics.
- [ ] **Public access** is implicitly disabled (no public subnets passed). Confirm.
- [ ] **In-VPC SG**: ingress from `10.0.0.0/16` is broad — tighten to specific node-group SG IDs in prod.
- [ ] **MSK Connect** for source/sink connectors (Kafka Connect): not in this module. Add separately if you don't run KC on EKS.

## Cost
- 3 × `kafka.t3.small`: ~$100/month
- 3 × 100 GB gp3: ~$30/month
- Data transfer in-VPC: free; cross-AZ replication: $0.02/GB

## Disaster recovery
- MSK Multi-AZ replication is automatic with 3 AZs.
- For cross-region DR: use MirrorMaker 2 (out of scope here).
