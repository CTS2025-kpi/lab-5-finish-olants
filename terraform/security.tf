############################################
# Security Groups
############################################

# ALB Security Group: allow inbound HTTP from internet; outbound anywhere
resource "aws_security_group" "alb" {
  name        = "${local.name}-alb-sg"
  description = "ALB SG"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Public access to API (HTTP)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # NOTE: SSH to ALB SG is not needed (ALB is not an EC2 you SSH into).
  # Remove SSH rules unless you explicitly need them for something else.

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-alb-sg" }
}

# ECS Tasks SG (rules managed separately to avoid drift issues)
resource "aws_security_group" "tasks" {
  name        = "${local.name}-tasks-sg"
  description = "ECS tasks SG"
  vpc_id      = aws_vpc.this.id

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-tasks-sg" }
}

############################################
# Security Group Rules (managed separately)
############################################

# ALB -> Coordinator (app port)
resource "aws_security_group_rule" "tasks_from_alb_app" {
  type                     = "ingress"
  security_group_id        = aws_security_group.tasks.id
  from_port                = var.container_port
  to_port                  = var.container_port
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  description              = "From ALB to coordinator on app port"
}

# Task-to-task app traffic (coordinator <-> shards) on app port
resource "aws_security_group_rule" "tasks_to_tasks_app" {
  type              = "ingress"
  security_group_id = aws_security_group.tasks.id
  from_port         = var.container_port
  to_port           = var.container_port
  protocol          = "tcp"
  self              = true
  description       = "Task-to-task app traffic on app port"
}

# Task-to-task AMQP (RabbitMQ) on 5672
resource "aws_security_group_rule" "tasks_to_tasks_amqp" {
  type              = "ingress"
  security_group_id = aws_security_group.tasks.id
  from_port         = 5672
  to_port           = 5672
  protocol          = "tcp"
  self              = true
  description       = "Task-to-task AMQP (RabbitMQ)"
}

# Optional: allow access to RabbitMQ management UI from within VPC (tasks only).
# If you don't need the management UI, remove this.
resource "aws_security_group_rule" "tasks_to_tasks_rabbitmq_mgmt" {
  type              = "ingress"
  security_group_id = aws_security_group.tasks.id
  from_port         = 15672
  to_port           = 15672
  protocol          = "tcp"
  self              = true
  description       = "Task-to-task RabbitMQ management UI (15672)"
}

# Optional: SSH (not used by Fargate tasks). Keep ONLY if you have a specific reason.
# If you keep it, it only allows inbound SSH *to tasks ENIs* (usually pointless).
resource "aws_security_group_rule" "tasks_ssh" {
  type              = "ingress"
  security_group_id = aws_security_group.tasks.id
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = ["213.110.152.29/32"]
  description       = "SSH access (usually unnecessary for Fargate)"
}
