resource "aws_cloudwatch_log_group" "coordinator" {
  name              = "/ecs/${local.name}/coordinator"
  retention_in_days = 1
}

resource "aws_cloudwatch_log_group" "shards" {
  for_each          = toset(local.shard_names)
  name              = "/ecs/${local.name}/${each.key}"
  retention_in_days = 1
}
