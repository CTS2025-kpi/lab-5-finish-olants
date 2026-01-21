resource "aws_ecs_cluster" "this" {
  name = "${local.name}-cluster"
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name = aws_ecs_cluster.this.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# Coordinator task definition
resource "aws_ecs_task_definition" "coordinator" {
  family                   = "${local.name}-coordinator"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.coordinator_cpu
  memory                   = var.coordinator_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "coordinator"
      image     = var.coordinator_image
      essential = true
      portMappings = [
        { containerPort = var.container_port, hostPort = var.container_port, protocol = "tcp" }
      ]
      environment = [
        { name = "PORT", value = tostring(var.container_port) },
        { name = "CLOUDMAP_NAMESPACE", value = var.cloudmap_namespace },
        { name = "SERVICE_NAME", value = "coordinator" },
        { name = "CLUSTER_NAME", value = local.name },
        { name = "METRICS_NAMESPACE", value = "ShardedKV" },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "BUILD_VERSION", value = "lab5-${timestamp()}" }      
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.coordinator.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

# Shard task definitions: one per shard, so each shard can have unique env vars and log group
resource "aws_ecs_task_definition" "shard" {
  for_each = toset(local.shard_names)

  family                   = "${local.name}-${each.key}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.shard_cpu
  memory                   = var.shard_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "shard"
      image     = var.shard_image
      essential = true
      portMappings = [
        { containerPort = var.container_port, hostPort = var.container_port, protocol = "tcp" }
      ]
      environment = [
        { name = "PORT", value = tostring(var.container_port) },
        { name = "COORDINATOR_URL", value = "http://coordinator.${var.cloudmap_namespace}:${var.container_port}" },
        { name = "SHARD_NAME", value = each.key },
        { name = "SHARD_URL", value = "http://${each.key}.${var.cloudmap_namespace}:${var.container_port}" },
        { name = "RABBITMQ_URL", value = "amqp://guest:guest@rabbitmq.${var.cloudmap_namespace}:5672/" },
        { name = "REPLICA_ID", value = "auto" },
        { name = "REGISTER_INTERVAL_SEC", value = "10" },
        { name = "SERVICE_NAME", value = "shard" },
        { name = "CLUSTER_NAME", value = local.name },
        { name = "METRICS_NAMESPACE", value = "ShardedKV" },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "RABBITMQ_QUEUE", value = "${each.key}-events" },
        { name = "BUILD_VERSION", value = "lab5-${timestamp()}" }


      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.shards[each.key].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

# Coordinator service (public via ALB)
resource "aws_ecs_service" "coordinator" {
  name                   = "coordinator"
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.coordinator.arn
  desired_count          = 1
  launch_type            = "FARGATE"
  enable_execute_command = true
  force_new_deployment   = true

  network_configuration {
    subnets          = [for s in aws_subnet.private : s.id]
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.coordinator.arn
    container_name   = "coordinator"
    container_port   = var.container_port
  }

  service_registries {
    registry_arn = aws_service_discovery_service.coordinator.arn
  }

  depends_on = [aws_lb_listener.http]
}

# Shard services (private, discovered via Cloud Map)
resource "aws_ecs_service" "shards" {
  for_each = toset(local.shard_names)

  name                   = each.key
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.shard[each.key].arn
  desired_count          = var.shard_min_count
  launch_type            = "FARGATE"
  enable_execute_command = true

  network_configuration {
    subnets          = [for s in aws_subnet.private : s.id]
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.shards[each.key].arn
  }

  depends_on = [aws_ecs_service.coordinator, aws_ecs_service.rabbitmq]
}

resource "aws_ecs_task_definition" "rabbitmq" {
  family                   = "${local.name}-rabbitmq"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "rabbitmq"
      image     = "rabbitmq:3-management"
      essential = true
      portMappings = [
        { containerPort = 5672, hostPort = 5672, protocol = "tcp" },
        { containerPort = 15672, hostPort = 15672, protocol = "tcp" }
      ]
      environment = []
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.coordinator.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "rabbitmq"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "rabbitmq" {
  name                   = "rabbitmq"
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.rabbitmq.arn
  desired_count          = 1
  launch_type            = "FARGATE"
  enable_execute_command = true

  network_configuration {
    subnets          = [for s in aws_subnet.private : s.id]
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }



  service_registries {
    registry_arn = aws_service_discovery_service.rabbitmq.arn
  }
}
