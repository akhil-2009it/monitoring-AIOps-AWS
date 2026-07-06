output "resource_arn" {
  value = aws_s3_bucket.buckets["raw"].arn
}

output "resource_name" {
  value = aws_s3_bucket.buckets["raw"].bucket
}

output "resource_id" {
  value = aws_s3_bucket.buckets["raw"].id
}

output "raw_bucket_name" {
  value = aws_s3_bucket.buckets["raw"].bucket
}

output "raw_bucket_arn" {
  value = aws_s3_bucket.buckets["raw"].arn
}

output "processed_bucket_name" {
  value = aws_s3_bucket.buckets["processed"].bucket
}

output "features_bucket_name" {
  value = aws_s3_bucket.buckets["features"].bucket
}

output "models_bucket_name" {
  value = aws_s3_bucket.buckets["models"].bucket
}

output "anomalies_bucket_name" {
  value = aws_s3_bucket.buckets["anomalies"].bucket
}

output "anomalies_bucket_arn" {
  value = aws_s3_bucket.buckets["anomalies"].arn
}

output "security_lake_bucket_name" {
  value = aws_s3_bucket.buckets["security_lake"].bucket
}

output "security_lake_bucket_arn" {
  value = aws_s3_bucket.buckets["security_lake"].arn
}

output "datalake_kms_key_arn" {
  value = aws_kms_key.datalake.arn
}

output "glue_database_name" {
  value = aws_glue_catalog_database.main.name
}

output "all_bucket_arns" {
  value = { for k, v in aws_s3_bucket.buckets : k => v.arn }
}
