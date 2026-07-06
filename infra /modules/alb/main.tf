locals {
  prefix = "${var.project}-${var.environment}"
}

# ─── Security Group ──────────────────────────────────────────────────────────
resource "aws_security_group" "alb" {
  name        = "${local.prefix}-api-alb-sg"
  description = "ALB SG: allow 443 from internet, 80 redirect"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP for redirect"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.prefix}-api-alb-sg" })
}

# ─── ALB ──────────────────────────────────────────────────────────────────────
resource "aws_lb" "api" {
  name               = "${local.prefix}-api-alb"
  internal           = var.internal
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection       = var.environment == "prod"
  enable_http2                     = true
  drop_invalid_header_fields       = true
  enable_cross_zone_load_balancing = true

  dynamic "access_logs" {
    for_each = var.access_logs_bucket != "" ? [1] : []
    content {
      bucket  = var.access_logs_bucket
      prefix  = "alb/${local.prefix}-api"
      enabled = true
    }
  }

  tags = merge(var.tags, { Name = "${local.prefix}-api-alb" })
}

# ─── Target Group ─────────────────────────────────────────────────────────────
# The actual target registration is done by the AWS Load Balancer Controller
# in EKS via TargetGroupBinding (in the helm chart).
resource "aws_lb_target_group" "api" {
  name        = "${local.prefix}-api-tg"
  port        = 8086
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 3
    interval            = 10
    matcher             = "200"
  }

  deregistration_delay = 30 # match SIGTERM grace

  tags = merge(var.tags, { Name = "${local.prefix}-api-tg" })
}

# ─── HTTP → HTTPS redirect ───────────────────────────────────────────────────
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# ─── HTTPS Listener ──────────────────────────────────────────────────────────
resource "aws_lb_listener" "https" {
  count = var.acm_certificate_arn != "" ? 1 : 0

  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  # If Cognito is wired, the ALB does OIDC auth before forwarding.
  default_action {
    type = var.cognito_user_pool_arn != "" ? "authenticate-cognito" : "forward"

    dynamic "authenticate_cognito" {
      for_each = var.cognito_user_pool_arn != "" ? [1] : []
      content {
        user_pool_arn              = var.cognito_user_pool_arn
        user_pool_client_id        = var.cognito_user_pool_client_id
        user_pool_domain           = var.cognito_user_pool_domain
        scope                      = "openid email profile"
        on_unauthenticated_request = "authenticate"
      }
    }

    target_group_arn = aws_lb_target_group.api.arn
  }
}

# Forward only — for endpoints that should bypass Cognito (e.g. /health for ALB target health)
resource "aws_lb_listener_rule" "health_bypass" {
  count = var.acm_certificate_arn != "" ? 1 : 0

  listener_arn = aws_lb_listener.https[0].arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern { values = ["/health"] }
  }
}

# ─── WAF Association ─────────────────────────────────────────────────────────
resource "aws_wafv2_web_acl_association" "api" {
  count = var.waf_web_acl_arn != "" ? 1 : 0

  resource_arn = aws_lb.api.arn
  web_acl_arn  = var.waf_web_acl_arn
}
