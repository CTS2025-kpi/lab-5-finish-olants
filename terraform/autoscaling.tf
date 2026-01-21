variable "shard_min_count" {
  type    = number
  default = 3
}

variable "shard_max_count" {
  type    = number
  default = 12
}

variable "shard_p99_scale_up_threshold_ms" {
  type    = number
  default = 1
}

variable "shard_scale_down_minutes" {
  type    = number
  default = 5
}

# Scalable target per shard ECS service
resource "aws_appautoscaling_target" "shards" {
  for_each           = toset(local.shard_names)
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"

  resource_id = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.shards[each.key].name}"

  min_capacity = var.shard_min_count
  max_capacity = var.shard_max_count
}

# Scale UP policy (+1)
resource "aws_appautoscaling_policy" "shard_scale_up" {
  for_each           = toset(local.shard_names)
  name               = "${local.name}-${each.key}-scale-up"
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = aws_appautoscaling_target.shards[each.key].resource_id

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 60
    metric_aggregation_type = "Average"

    step_adjustment {
      metric_interval_lower_bound = 0
      scaling_adjustment          = 1
    }
  }
}

# Scale DOWN policy (-1)
resource "aws_appautoscaling_policy" "shard_scale_down" {
  for_each           = toset(local.shard_names)
  name               = "${local.name}-${each.key}-scale-down"
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = aws_appautoscaling_target.shards[each.key].resource_id

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 120
    metric_aggregation_type = "Average"

    step_adjustment {
      metric_interval_upper_bound = 0
      scaling_adjustment          = -1
    }
  }
}

# Alarm: p99 latency > threshold -> scale UP
resource "aws_cloudwatch_metric_alarm" "shard_p99_latency_high" {
  for_each = toset(local.shard_names)

  alarm_name          = "${local.name}-${each.key}-p99-latency-high"
  comparison_operator = "GreaterThanThreshold"

  period              = 60
  evaluation_periods  = 2
  datapoints_to_alarm = 2

  threshold          = var.shard_p99_scale_up_threshold_ms
  treat_missing_data = "notBreaching"

  namespace          = "ShardedKV"
  metric_name        = "RequestLatencyMs"
  extended_statistic = "p99"

  dimensions = {
    Cluster = local.name
    Service = "shard"
    Shard   = each.key
  }

  alarm_actions = [aws_appautoscaling_policy.shard_scale_up[each.key].arn]
}

# Alarm: p99 latency < threshold for N minutes -> scale DOWN
resource "aws_cloudwatch_metric_alarm" "shard_p99_latency_low" {
  for_each = toset(local.shard_names)

  alarm_name          = "${local.name}-${each.key}-p99-latency-low"
  comparison_operator = "LessThanThreshold"

  period              = 60
  evaluation_periods  = var.shard_scale_down_minutes
  datapoints_to_alarm = var.shard_scale_down_minutes

  threshold          = var.shard_p99_scale_up_threshold_ms
  treat_missing_data = "notBreaching"

  namespace          = "ShardedKV"
  metric_name        = "RequestLatencyMs"
  extended_statistic = "p99"

  dimensions = {
    Cluster = local.name
    Service = "shard"
    Shard   = each.key
  }

  alarm_actions = [aws_appautoscaling_policy.shard_scale_down[each.key].arn]
}

