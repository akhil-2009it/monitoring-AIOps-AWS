# demo-app/infra — Production Checklist

Demo workloads are usually NOT a production concern, but if you do deploy
to a customer-facing environment:

- [ ] Set `environment = "prod"` and re-apply. Triggers Multi-AZ RDS,
  deletion protection, no skip_final_snapshot.
- [ ] Override `rds_instance_class` (default `db.t3.micro`) — too small for
  any sustained traffic.
- [ ] Provision a DNS record (`aws_route53_record`) for the demo hostname
  pointing at the ALB created by the demo-web Ingress.
- [ ] Issue an ACM certificate matching the hostname; set the cert ARN in
  the demo-web Helm values (`alb.ingress.kubernetes.io/certificate-arn`).
- [ ] Attach a WAF ACL to the ALB Ingress (`alb.ingress.kubernetes.io/wafv2-acl-arn`)
  — reuse the platform's WAF or create a tighter one for the demo.
- [ ] Configure a CloudFront distribution in front of the ALB:
  - origin = the ALB DNS name
  - cache policy = managed `CachingDisabled` for `/api/*`, `CachingOptimized` for `/`
  - logging enabled to a bucket that the platform's Firehose can pick up
- [ ] Enable Redis transit encryption (`transit_encryption_enabled = true`) and
  switch the worker `REDIS_URL` to use TLS.
- [ ] Consider Aurora Serverless v2 instead of single-instance MySQL for
  variable-load demos.

## Cost (dev defaults)
- RDS db.t3.micro:        ~$0.40/day
- ElastiCache cache.t3.micro: ~$0.30/day
- ALB (per Ingress):      ~$0.60/day base
- ECR storage:            negligible
- CloudWatch logs ingest: ~$0.05/day at demo scale

**Total demo daily floor: ~$1.50–2.00/day on top of the AIOps platform.**
