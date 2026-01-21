resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "n8n" {
  count     = var.n8n_sns_endpoint != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "https"
  endpoint  = var.n8n_sns_endpoint
}
variable "p99_latency_ms_threshold" {
  type    = number
  default = 300
}

variable "repl_lag_ms_threshold" {
  type    = number
  default = 5000
}

resource "aws_cloudwatch_metric_alarm" "coordinator_p99_latency" {
  alarm_name          = "${local.name}-coordinator-p99-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  period              = 60
  threshold           = var.p99_latency_ms_threshold
  treat_missing_data  = "notBreaching"

  namespace          = "ShardedKV"
  metric_name        = "RequestLatencyMs"
  extended_statistic = "p99"

  dimensions = {
    Cluster = local.name
    Service = "coordinator"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "replication_lag" {
  alarm_name          = "${local.name}-replication-lag"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  period              = 60
  threshold           = var.repl_lag_ms_threshold
  treat_missing_data  = "notBreaching"

  namespace          = "ShardedKV"
  metric_name        = "ReplicationLagMs"
  extended_statistic = "p99"

  dimensions = {
    Cluster = local.name
    Service = "shard"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "shard_heartbeat_missing" {
  alarm_name          = "${local.name}-shard-heartbeat-missing"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  period              = 60
  threshold           = 1
  treat_missing_data  = "breaching"

  namespace   = "ShardedKV"
  metric_name = "Heartbeat"
  statistic   = "Sum"

  dimensions = {
    Cluster = local.name
    Service = "shard"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "shard_service_heartbeat_missing" {
  for_each = toset(local.shard_names)

  alarm_name          = "${local.name}-${each.key}-heartbeat-missing"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  period              = 60
  threshold           = 1
  treat_missing_data  = "breaching"

  namespace   = "ShardedKV"
  metric_name = "Heartbeat"
  statistic   = "Sum"

  dimensions = {
    Cluster = local.name
    Service = "shard"
    Shard   = each.key
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "replication_lag_per_shard" {
  for_each = toset(local.shard_names)

  alarm_name          = "${local.name}-${each.key}-replication-lag"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  period              = 60
  threshold           = var.repl_lag_ms_threshold
  treat_missing_data  = "notBreaching"

  namespace          = "ShardedKV"
  metric_name        = "ReplicationLagMs"
  extended_statistic = "p99"

  dimensions = {
    Cluster = local.name
    Service = "shard"
    Shard   = each.key
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

