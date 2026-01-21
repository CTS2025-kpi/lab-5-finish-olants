resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = var.cloudmap_namespace
  description = "Private DNS namespace for sharded lab"
  vpc         = aws_vpc.this.id
}

resource "aws_service_discovery_service" "coordinator" {
  name = "coordinator"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {

  }

}

resource "aws_service_discovery_service" "shards" {
  for_each = toset(local.shard_names)
  name     = each.key

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {

  }

}

resource "aws_service_discovery_service" "rabbitmq" {
  name = "rabbitmq"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {

  }
}
