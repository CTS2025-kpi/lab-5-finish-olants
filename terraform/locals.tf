locals {
  name = var.project_name

  shard_names = [
    for i in range(1, var.shard_count + 1) : "shard-${i}"
  ]
}
