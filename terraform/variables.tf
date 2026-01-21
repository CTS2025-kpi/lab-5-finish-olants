variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Prefix for all resources"
  default     = "sharded-lab"
}

variable "vpc_cidr" {
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  type        = number
  default     = 2
}

variable "coordinator_image" {
  type        = string
  description = "Container image for coordinator (ECR URI or public image)"
  default     = "702958405735.dkr.ecr.us-east-1.amazonaws.com/coordinator:lab5"
}

variable "shard_image" {
  type        = string
  description = "Container image for shard (ECR URI or public image)"
  default     = "702958405735.dkr.ecr.us-east-1.amazonaws.com/shard:lab5"
}

variable "shard_min_tasks" {
  type    = number
  default = 3
}

variable "coordinator_cpu" {
  type    = number
  default = 256
}

variable "coordinator_memory" {
  type    = number
  default = 512
}

variable "shard_cpu" {
  type    = number
  default = 256
}

variable "shard_memory" {
  type    = number
  default = 512
}

variable "shard_count" {
  type        = number
  description = "How many shard services to run"
  default     = 3
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "cloudmap_namespace" {
  type    = string
  default = "sharded.local"
}

variable "shard_p99_latency_scaleout_threshold_ms" {
  type    = number
  default = 300
}

variable "shard_scaleout_step" {
  type    = number
  default = 1
}

variable "shard_autoscale_min_capacity" {
  type    = number
  default = 3
}

variable "shard_autoscale_max_capacity" {
  type    = number
  default = 12
}