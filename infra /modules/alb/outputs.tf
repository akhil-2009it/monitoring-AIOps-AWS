output "alb_arn" { value = aws_lb.api.arn }
output "alb_dns_name" { value = aws_lb.api.dns_name }
output "alb_zone_id" { value = aws_lb.api.zone_id }
output "target_group_arn" { value = aws_lb_target_group.api.arn }
output "security_group_id" { value = aws_security_group.alb.id }
