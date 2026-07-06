locals {
  prefix = "${var.project}-${var.environment}"
}

resource "aws_wafv2_web_acl" "api" {
  name        = "${local.prefix}-api-acl"
  description = "WAF for ${local.prefix} Recommendation API ALB"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # 1. AWS Managed: Common attacks (XSS, body size, etc.)
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-common-rules"
      sampled_requests_enabled   = true
    }
  }

  # 2. Known bad inputs (SQLi-shaped payloads, header injection)
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  # 3. SQL injection
  rule {
    name     = "AWSManagedRulesSQLiRuleSet"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesSQLiRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-sqli"
      sampled_requests_enabled   = true
    }
  }

  # 4. Anonymous IPs (Tor, hosting providers, VPN)
  rule {
    name     = "AWSManagedRulesAnonymousIpList"
    priority = 4

    override_action {
      count {} # count-only by default; switch to none{} to block
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAnonymousIpList"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-anonymous-ip"
      sampled_requests_enabled   = true
    }
  }

  # 5. Per-IP rate limit
  rule {
    name     = "RateLimitPerIP"
    priority = 10

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.rate_limit_per_5min
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.prefix}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  # 6. Optional geo-blocking
  dynamic "rule" {
    for_each = length(var.blocked_country_codes) > 0 ? [1] : []

    content {
      name     = "GeoBlock"
      priority = 20

      action {
        block {}
      }

      statement {
        geo_match_statement {
          country_codes = var.blocked_country_codes
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.prefix}-geo-block"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.prefix}-api-acl"
    sampled_requests_enabled   = true
  }

  tags = merge(var.tags, { Name = "${local.prefix}-api-acl" })
}

resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-${local.prefix}-api"
  retention_in_days = 30
  tags              = var.tags
}

resource "aws_wafv2_web_acl_logging_configuration" "api" {
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
  resource_arn            = aws_wafv2_web_acl.api.arn

  redacted_fields {
    single_header { name = "authorization" }
  }
  redacted_fields {
    single_header { name = "cookie" }
  }
}
