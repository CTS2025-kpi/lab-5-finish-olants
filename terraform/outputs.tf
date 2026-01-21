output "coordinator_url" {
  description = "Public URL (HTTP) for coordinator via ALB"
  value       = "http://${aws_lb.alb.dns_name}"
}

output "cloudmap_namespace" {
  value = aws_service_discovery_private_dns_namespace.this.name
}
